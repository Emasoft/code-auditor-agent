# fixture for library_c — build glue is irrelevant; what matters is
# that CMakeLists.txt + include/*.h + src/*.c trigger the library_c
# fingerprint and nothing else.

cmake_minimum_required(VERSION 3.10)
project(mylibc C)

add_library(mylibc STATIC src/mylib.c)
target_include_directories(mylibc PUBLIC include)
