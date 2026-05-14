# fixture for game_engine
cmake_minimum_required(VERSION 3.20)
project(SampleEngine CXX)

set(CMAKE_CXX_STANDARD 20)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

add_executable(sample_engine
    src/main.cpp
    src/Engine.cpp
)

target_include_directories(sample_engine PRIVATE src)
