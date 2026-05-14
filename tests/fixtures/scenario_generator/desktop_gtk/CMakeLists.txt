# fixture for desktop_gtk
cmake_minimum_required(VERSION 3.16)
project(demo_gtk_app C)

find_package(PkgConfig REQUIRED)
pkg_check_modules(GTK4 REQUIRED gtk4)

add_executable(demo_gtk_app main.c)
target_include_directories(demo_gtk_app PRIVATE ${GTK4_INCLUDE_DIRS})
target_link_libraries(demo_gtk_app PRIVATE ${GTK4_LIBRARIES})
