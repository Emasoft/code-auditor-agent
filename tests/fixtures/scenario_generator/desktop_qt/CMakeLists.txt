# fixture for desktop_qt
cmake_minimum_required(VERSION 3.16)
project(demo_qt_app LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_AUTOMOC ON)

find_package(Qt6 REQUIRED COMPONENTS Widgets)

add_executable(demo_qt_app main.cpp MainWindow.cpp MainWindow.h)
target_link_libraries(demo_qt_app PRIVATE Qt6::Widgets)
