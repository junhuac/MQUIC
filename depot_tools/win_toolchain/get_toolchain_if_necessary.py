#!/usr/bin/env python
# Copyright 2013 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Downloads and unpacks a toolchain for building on Windows. The contents are
matched by sha1 which will be updated when the toolchain is updated.

Having a toolchain script in depot_tools means that it's not versioned
directly with the source code. That is, if the toolchain is upgraded, but
you're trying to build an historical version of Chromium from before the
toolchain upgrade, this will cause you to build with a newer toolchain than
was available when that code was committed. This is done for a two main
reasons: 1) it would likely be annoying to have the up-to-date toolchain
removed and replaced by one without a service pack applied); 2) it would
require maintaining scripts that can build older not-up-to-date revisions of
the toolchain. This is likely to be a poorly tested code path that probably
won't be properly maintained. See http://crbug.com/323300.

This does not extend to major versions of the toolchain however, on the
assumption that there are more likely to be source incompatibilities between
major revisions. This script calls a subscript (currently, toolchain2013.py)
to do the main work. It is expected that toolchain2013.py will always be able
to acquire/build the most current revision of a VS2013-based toolchain. In the
future when a hypothetical VS2015 is released, the 2013 script will be
maintained, and a new 2015 script would be added.
"""

import hashlib
import json
import optparse
import os
import platform
import shutil
import subprocess
import sys
import tempfile
import time
import zipfile

# winreg isn't natively available under CygWin
if sys.platform == "win32":
  try:
    import winreg
  except ImportError:
    import _winreg as winreg
elif sys.platform == "cygwin":
  try:
    import cygwinreg as winreg
  except ImportError:
    print ''
    print 'CygWin does not natively support winreg but a replacement exists.'
    print 'https://pypi.python.org/pypi/cygwinreg/'
    print ''
    print 'Try: easy_install cygwinreg'
    print ''
    raise

BASEDIR = os.path.dirname(os.path.abspath(__file__))
DEPOT_TOOLS_PATH = os.path.join(BASEDIR, '..')
sys.path.append(DEPOT_TOOLS_PATH)
try:
  import download_from_google_storage
except ImportError:
  # Allow use of utility functions in this script from package_from_installed
  # on bare VM that doesn't have a full depot_tools.
  pass


def GetFileList(root):
  """Gets a normalized list of files under |root|."""
  assert not os.path.isabs(root)
  assert os.path.normpath(root) == root
  file_list = []
  for base, _, files in os.walk(root):
    paths = [os.path.join(base, f) for f in files]
    # Ignore WER ReportQueue entries that vctip/cl leave in the bin dir if/when
    # they crash.
    file_list.extend(x.lower() for x in paths if 'WER\\ReportQueue' not in x)
  return sorted(file_list, key=lambda s: s.replace('/', '\\'))


def MakeTimestampsFileName(root, sha1):
  return os.path.join(root, os.pardir, '%s.timestamps' % sha1)


def CalculateHash(root, expected_hash):
  """Calculates the sha1 of the paths to all files in the given |root| and the
  contents of those files, and returns as a hex string.

  |expected_hash| is the expected hash value for this toolchain if it has
  already been installed.
  """
  if expected_hash:
    full_root_path = os.path.join(root, expected_hash)
  else:
    full_root_path = root
  file_list = GetFileList(full_root_path)
  # Check whether we previously saved timestamps in $root/../{sha1}.timestamps.
  # If we didn't, or they don't match, then do the full calculation, otherwise
  # return the saved value.
  timestamps_file = MakeTimestampsFileName(root, expected_hash)
  timestamps_data = {'files': [], 'sha1': ''}
  if os.path.exists(timestamps_file):
    with open(timestamps_file, 'rb') as f:
      try:
        timestamps_data = json.load(f)
      except ValueError:
        # json couldn't be loaded, empty data will force a re-hash.
        pass

  matches = len(file_list) == len(timestamps_data['files'])
  # Don't check the timestamp of the version file as we touch this file to
  # indicates which versions of the toolchain are still being used.
  vc_dir = os.path.join(full_root_path, 'VC').lower()
  if matches:
    for disk, cached in zip(file_list, timestamps_data['files']):
      if disk != cached[0] or (
          disk != vc_dir and os.path.getmtime(disk) != cached[1]):
        matches = False
        break
  if matches:
    return timestamps_data['sha1']

  # Make long hangs when updating the toolchain less mysterious.
  print 'Calculating hash of toolchain in %s. Please wait...' % full_root_path
  sys.stdout.flush()
  digest = hashlib.sha1()
  for path in file_list:
    path_without_hash = str(path).replace('/', '\\')
    if expected_hash:
      path_without_hash = path_without_hash.replace(
          os.path.join(root, expected_hash).replace('/', '\\'), root)
    digest.update(path_without_hash)
    with open(path, 'rb') as f:
      digest.update(f.read())
  return digest.hexdigest()


def CalculateToolchainHashes(root):
  """Calculate the hash of the different toolchains installed in the |root|
  directory."""
  hashes = []
  dir_list = [
      d for d in os.listdir(root) if os.path.isdir(os.path.join(root, d))]
  for d in dir_list:
    hashes.append(CalculateHash(root, d))
  return hashes


def SaveTimestampsAndHash(root, sha1):
  """Saves timestamps and the final hash to be able to early-out more quickly
  next time."""
  file_list = GetFileList(os.path.join(root, sha1))
  timestamps_data = {
    'files': [[f, os.path.getmtime(f)] for f in file_list],
    'sha1': sha1,
  }
  with open(MakeTimestampsFileName(root, sha1), 'wb') as f:
    json.dump(timestamps_data, f)


def HaveSrcInternalAccess():
  """Checks whether access to src-internal is available."""
  with open(os.devnull, 'w') as nul:
    if subprocess.call(
        ['svn', 'ls', '--non-interactive',
         'svn://svn.chromium.org/chrome-internal/trunk/src-internal/'],
        shell=True, stdin=nul, stdout=nul, stderr=nul) == 0:
      return True
    return subprocess.call(
        ['git', '-c', 'core.askpass=true', 'remote', 'show',
         'https://chrome-internal.googlesource.com/chrome/src-internal/'],
        shell=True, stdin=nul, stdout=nul, stderr=nul) == 0


def LooksLikeGoogler():
  """Checks for a USERDOMAIN environment variable of 'GOOGLE', which
  probably implies the current user is a Googler."""
  return os.environ.get('USERDOMAIN', '').upper() == 'GOOGLE'


def CanAccessToolchainBucket():
  """Checks whether the user has access to gs://chrome-wintoolchain/."""
  gsutil = download_from_google_storage.Gsutil(
      download_from_google_storage.GSUTIL_DEFAULT_PATH, boto_path=None)
  code, _, _ = gsutil.check_call('ls', 'gs://chrome-wintoolchain/')
  return code == 0


def RequestGsAuthentication():
  """Requests that the user authenticate to be able to access gs:// as a
  Googler. This allows much faster downloads, and pulling (old) toolchains
  that match src/ revisions.
  """
  print 'Access to gs://chrome-wintoolchain/ not configured.'
  print '-----------------------------------------------------------------'
  print
  print 'You appear to be a Googler.'
  print
  print 'I\'m sorry for the hassle, but you need to do a one-time manual'
  print 'authentication. Please run:'
  print
  print '    download_from_google_storage --config'
  print
  print 'and follow the instructions.'
  print
  print 'NOTE 1: Use your google.com credentials, not chromium.org.'
  print 'NOTE 2: Enter 0 when asked for a "project-id".'
  print
  print '-----------------------------------------------------------------'
  print
  sys.stdout.flush()
  sys.exit(1)


def DelayBeforeRemoving(target_dir):
  """A grace period before deleting the out of date toolchain directory."""
  if (os.path.isdir(target_dir) and
      not bool(int(os.environ.get('CHROME_HEADLESS', '0')))):
    for i in range(9, 0, -1):
      sys.stdout.write(
              '\rRemoving old toolchain in %ds... (Ctrl-C to cancel)' % i)
      sys.stdout.flush()
      time.sleep(1)
    print


def DownloadUsingGsutil(filename):
  """Downloads the given file from Google Storage chrome-wintoolchain bucket."""
  temp_dir = tempfile.mkdtemp()
  assert os.path.basename(filename) == filename
  target_path = os.path.join(temp_dir, filename)
  gsutil = download_from_google_storage.Gsutil(
      download_from_google_storage.GSUTIL_DEFAULT_PATH, boto_path=None)
  code = gsutil.call('cp', 'gs://chrome-wintoolchain/' + filename, target_path)
  if code != 0:
    sys.exit('gsutil failed')
  return temp_dir, target_path


def RmDir(path):
  """Deletes path and all the files it contains."""
  if sys.platform != 'win32':
    shutil.rmtree(path, ignore_errors=True)
  else:
    # shutil.rmtree() doesn't delete read-only files on Windows.
    subprocess.check_call('rmdir /s/q "%s"' % path, shell=True)


def DoTreeMirror(target_dir, tree_sha1):
  """In order to save temporary space on bots that do not have enough space to
  download ISOs, unpack them, and copy to the target location, the whole tree
  is uploaded as a zip to internal storage, and then mirrored here."""
  use_local_zip = bool(int(os.environ.get('USE_LOCAL_ZIP', 0)))
  if use_local_zip:
    temp_dir = None
    local_zip = tree_sha1 + '.zip'
  else:
    temp_dir, local_zip = DownloadUsingGsutil(tree_sha1 + '.zip')
  sys.stdout.write('Extracting %s...\n' % local_zip)
  sys.stdout.flush()
  with zipfile.ZipFile(local_zip, 'r', zipfile.ZIP_DEFLATED, True) as zf:
    zf.extractall(target_dir)
  if temp_dir:
    RmDir(temp_dir)


def RemoveToolchain(root, sha1, delay_before_removing):
  """Remove the |sha1| version of the toolchain from |root|."""
  toolchain_target_dir = os.path.join(root, sha1)
  if delay_before_removing:
    DelayBeforeRemoving(toolchain_target_dir)
  if sys.platform == 'win32':
    # These stay resident and will make the rmdir below fail.
    kill_list = [
      'mspdbsrv.exe',
      'vctip.exe', # Compiler and tools experience improvement data uploader.
    ]
    for process_name in kill_list:
      with open(os.devnull, 'wb') as nul:
        subprocess.call(['taskkill', '/f', '/im', process_name],
                        stdin=nul, stdout=nul, stderr=nul)
  if os.path.isdir(toolchain_target_dir):
    RmDir(toolchain_target_dir)

  timestamp_file = MakeTimestampsFileName(root, sha1)
  if os.path.exists(timestamp_file):
    os.remove(timestamp_file)


def RemoveUnusedToolchains(root):
  """Remove the versions of the toolchain that haven't been used recently."""
  valid_toolchains = []
  dirs_to_remove = []

  for d in os.listdir(root):
    full_path = os.path.join(root, d)
    if os.path.isdir(full_path):
      if not os.path.exists(MakeTimestampsFileName(root, d)):
        dirs_to_remove.append(d)
      else:
        vc_dir = os.path.join(full_path, 'VC')
        valid_toolchains.append((os.path.getmtime(vc_dir), d))
    elif os.path.isfile(full_path):
      os.remove(full_path)

  for d in dirs_to_remove:
    print ('Removing %s as it doesn\'t correspond to any known toolchain.' %
           os.path.join(root, d))
    # Use the RemoveToolchain function to remove these directories as they might
    # contain an older version of the toolchain.
    RemoveToolchain(root, d, False)

  # Remove the versions of the toolchains that haven't been used in the past 30
  # days.
  toolchain_expiration_time = 60 * 60 * 24 * 30
  for toolchain in valid_toolchains:
    toolchain_age_in_sec = time.time() - toolchain[0]
    if toolchain_age_in_sec > toolchain_expiration_time:
      print ('Removing version %s of the Win toolchain has it hasn\'t been used'
             ' in the past %d days.' % (toolchain[1],
                                        toolchain_age_in_sec / 60 / 60 / 24))
      RemoveToolchain(root, toolchain[1], True)


def GetInstallerName():
  """Return the name of the Windows 10 Universal C Runtime installer for the
  current platform, or None if installer is not needed or not applicable.
  The registry has to be used instead of sys.getwindowsversion() because
  Python 2.7 is only manifested as being compatible up to Windows 8, so the
  version APIs helpfully return a maximum of 6.2 (Windows 8).
  """
  key_name = r'Software\Microsoft\Windows NT\CurrentVersion'
  key = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, key_name)
  value, keytype = winreg.QueryValueEx(key, "CurrentVersion")
  key.Close()
  if keytype != winreg.REG_SZ:
    raise Exception("Unexpected type in registry")
  if value == '6.1':
    # Windows 7 and Windows Server 2008 R2
    return 'Windows6.1-KB2999226-x64.msu'
  elif value == '6.2':
    # Windows 8 and Windows Server 2012
    return 'Windows8-RT-KB2999226-x64.msu'
  elif value == '6.3':
    # Windows 8.1, Windows Server 2012 R2, and Windows 10.
    # The Windows 8.1 installer doesn't work on Windows 10, but it will never
    # be used because the UCRT is always installed on Windows 10.
    return 'Windows8.1-KB2999226-x64.msu'
  else:
    # Some future OS.
    return None


def InstallUniversalCRTIfNeeded(abs_target_dir):
  return


def main():
  parser = optparse.OptionParser(description=sys.modules[__name__].__doc__)
  parser.add_option('--output-json', metavar='FILE',
                    help='write information about toolchain to FILE')
  parser.add_option('--force', action='store_true',
                    help='force script to run on non-Windows hosts')
  options, args = parser.parse_args()

  if not (sys.platform.startswith(('cygwin', 'win32')) or options.force):
    return 0

  if sys.platform == 'cygwin':
    # This script requires Windows Python, so invoke with depot_tools' Python.
    def winpath(path):
      return subprocess.check_output(['cygpath', '-w', path]).strip()
    python = os.path.join(DEPOT_TOOLS_PATH, 'python.bat')
    cmd = [python, winpath(__file__)]
    if options.output_json:
      cmd.extend(['--output-json', winpath(options.output_json)])
    cmd.extend(args)
    sys.exit(subprocess.call(cmd))
  assert sys.platform != 'cygwin'

  if len(args) == 0:
    sys.exit('Desired hash is required.')
  desired_hash = args[0]

  # Move to depot_tools\win_toolchain where we'll store our files, and where
  # the downloader script is.
  os.chdir(os.path.normpath(os.path.join(BASEDIR)))
  toolchain_dir = '.'
  if os.environ.get('GYP_MSVS_VERSION') == '2015':
    target_dir = os.path.normpath(os.path.join(toolchain_dir, 'vs_files'))
  else:
    target_dir = os.path.normpath(os.path.join(toolchain_dir, 'vs2013_files'))
  if not os.path.isdir(target_dir):
    os.mkdir(target_dir)
  toolchain_target_dir = os.path.join(target_dir, desired_hash)

  abs_toolchain_target_dir = os.path.abspath(toolchain_target_dir)

  got_new_toolchain = False

  # If the current hash doesn't match what we want in the file, nuke and pave.
  # Typically this script is only run when the .sha1 one file is updated, but
  # directly calling "gclient runhooks" will also run it, so we cache
  # based on timestamps to make that case fast.
  current_hashes = CalculateToolchainHashes(target_dir)
  if desired_hash not in current_hashes:
    should_use_gs = False
    if (HaveSrcInternalAccess() or
        LooksLikeGoogler() or
        CanAccessToolchainBucket()):
      should_use_gs = True
      if not CanAccessToolchainBucket():
        RequestGsAuthentication()
    if not should_use_gs:
      print('\n\n\nPlease follow the instructions at '
            'https://www.chromium.org/developers/how-tos/'
            'build-instructions-windows\n\n')
      return 1
    print('Windows toolchain out of date or doesn\'t exist, updating (Pro)...')
    print('  current_hashes: %s' % ', '.join(current_hashes))
    print('  desired_hash: %s' % desired_hash)
    sys.stdout.flush()

    DoTreeMirror(toolchain_target_dir, desired_hash)

    got_new_toolchain = True

  win_sdk = os.path.join(abs_toolchain_target_dir, 'win_sdk')
  try:
    version_file = os.path.join(toolchain_target_dir, 'VS_VERSION')
    vc_dir = os.path.join(toolchain_target_dir, 'VC')
    with open(version_file, 'rb') as f:
      vs_version = f.read().strip()
      # Touch the VC directory so we can use its timestamp to know when this
      # version of the toolchain has been used for the last time.
    os.utime(vc_dir, None)
  except IOError:
    # Older toolchains didn't have the VS_VERSION file, and used 'win8sdk'
    # instead of just 'win_sdk'.
    vs_version = '2013'
    win_sdk = os.path.join(abs_toolchain_target_dir, 'win8sdk')

  data = {
      'path': abs_toolchain_target_dir,
      'version': vs_version,
      'win_sdk': win_sdk,
      # Added for backwards compatibility with old toolchain packages.
      'win8sdk': win_sdk,
      'wdk': os.path.join(abs_toolchain_target_dir, 'wdk'),
      'runtime_dirs': [
        os.path.join(abs_toolchain_target_dir, 'sys64'),
        os.path.join(abs_toolchain_target_dir, 'sys32'),
      ],
  }
  with open(os.path.join(target_dir, '..', 'data.json'), 'w') as f:
    json.dump(data, f)

  if got_new_toolchain:
    current_hashes = CalculateToolchainHashes(target_dir)
    if desired_hash not in current_hashes:
      print >> sys.stderr, (
          'Got wrong hash after pulling a new toolchain. '
          'Wanted \'%s\', got one of \'%s\'.' % (
              desired_hash, ', '.join(current_hashes)))
      return 1
    SaveTimestampsAndHash(target_dir, desired_hash)

  if options.output_json:
    shutil.copyfile(os.path.join(target_dir, '..', 'data.json'),
                    options.output_json)

  if os.environ.get('GYP_MSVS_VERSION') == '2015':
    InstallUniversalCRTIfNeeded(abs_toolchain_target_dir)

  RemoveUnusedToolchains(target_dir)

  return 0


if __name__ == '__main__':
  sys.exit(main())
