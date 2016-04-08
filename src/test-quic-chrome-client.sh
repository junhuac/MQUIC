/Applications/Google\ Chrome.app/Contents/MacOS/Google\ Chrome \
  --user-data-dir=/tmp/chrome-profile \
  --no-proxy-server \
  --enable-quic \
  --origin-to-force-quic-on=www.example.org:443 \
  --host-resolver-rules='MAP www.example.org:443 127.0.0.1:6121' \
  https://www.example.org

