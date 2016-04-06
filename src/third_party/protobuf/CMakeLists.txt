cmake_minimum_required (VERSION 2.8.10)

project (libprotobuf)

include_directories(src .)

add_library(
	protobuf
	STATIC

	src/google/protobuf/extension_set.cc
	src/google/protobuf/extension_set.h
	src/google/protobuf/generated_message_util.cc
	src/google/protobuf/generated_message_util.h
	src/google/protobuf/io/coded_stream.cc
	src/google/protobuf/io/coded_stream.h
	src/google/protobuf/io/coded_stream_inl.h
	src/google/protobuf/io/zero_copy_stream.cc
	src/google/protobuf/io/zero_copy_stream.h
	src/google/protobuf/io/zero_copy_stream_impl_lite.cc
	src/google/protobuf/io/zero_copy_stream_impl_lite.h
	src/google/protobuf/message_lite.cc
	src/google/protobuf/message_lite.h
	src/google/protobuf/repeated_field.cc
	src/google/protobuf/repeated_field.h
	src/google/protobuf/stubs/atomicops.h
	src/google/protobuf/stubs/atomicops_internals_arm_gcc.h
	src/google/protobuf/stubs/atomicops_internals_atomicword_compat.h
	src/google/protobuf/stubs/atomicops_internals_macosx.h
	src/google/protobuf/stubs/atomicops_internals_mips_gcc.h
	src/google/protobuf/stubs/atomicops_internals_x86_gcc.cc
	src/google/protobuf/stubs/atomicops_internals_x86_gcc.h
	src/google/protobuf/stubs/atomicops_internals_x86_msvc.cc
	src/google/protobuf/stubs/atomicops_internals_x86_msvc.h
	src/google/protobuf/stubs/common.cc
	src/google/protobuf/stubs/common.h
	src/google/protobuf/stubs/hash.h
	src/google/protobuf/stubs/map-util.h
	src/google/protobuf/stubs/once.cc
	src/google/protobuf/stubs/once.h
	src/google/protobuf/stubs/platform_macros.h
	src/google/protobuf/unknown_field_set.cc
	src/google/protobuf/unknown_field_set.h
	src/google/protobuf/wire_format_lite.cc
	src/google/protobuf/wire_format_lite.h
	src/google/protobuf/wire_format_lite_inl.h
	config.h
)
