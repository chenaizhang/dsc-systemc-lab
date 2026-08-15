cmake_minimum_required(VERSION 3.20)
project(dsc_encoder_tlm_skeleton LANGUAGES CXX)

find_package(SystemCLanguage CONFIG QUIET)
if(NOT TARGET SystemC::systemc)
    find_path(SYSTEMC_INCLUDE_DIR systemc HINTS $ENV{SYSTEMC_HOME} PATH_SUFFIXES include)
    find_library(SYSTEMC_LIBRARY NAMES systemc HINTS $ENV{SYSTEMC_HOME} PATH_SUFFIXES lib lib64)
    if(NOT SYSTEMC_INCLUDE_DIR OR NOT SYSTEMC_LIBRARY)
        message(FATAL_ERROR "SystemC was not found. Set CMAKE_PREFIX_PATH or SYSTEMC_HOME.")
    endif()
    add_library(SystemC::systemc UNKNOWN IMPORTED)
    set_target_properties(SystemC::systemc PROPERTIES
        IMPORTED_LOCATION "${SYSTEMC_LIBRARY}"
        INTERFACE_INCLUDE_DIRECTORIES "${SYSTEMC_INCLUDE_DIR}")
endif()

add_executable(dsc_encoder_tlm main.cpp)
target_compile_features(dsc_encoder_tlm PRIVATE cxx_std_17)
target_link_libraries(dsc_encoder_tlm PRIVATE SystemC::systemc)
target_compile_options(dsc_encoder_tlm PRIVATE -Wall -Wextra -Wpedantic)
