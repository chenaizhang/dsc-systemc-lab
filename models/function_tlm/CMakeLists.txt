cmake_minimum_required(VERSION 3.20)
project(dsc_function_tlm LANGUAGES C CXX)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)

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

add_library(dsc_function_tlm INTERFACE)
target_include_directories(dsc_function_tlm INTERFACE
    ${CMAKE_CURRENT_SOURCE_DIR}/include
    ${CMAKE_CURRENT_SOURCE_DIR}/../dataflow_systemc
)
target_link_libraries(dsc_function_tlm INTERFACE SystemC::systemc)

option(DSCFLOW_ENABLE_VESA_CODEC
    "Build the pure function adapter for the separately downloaded VESA DSC C model" OFF)
set(VESA_DSC_MODEL_ROOT "" CACHE PATH
    "Directory containing the VESA DSC_model_20211213 source/ directory")

if(DSCFLOW_ENABLE_VESA_CODEC)
    if(NOT EXISTS "${VESA_DSC_MODEL_ROOT}/source/dsc_codec.c")
        message(FATAL_ERROR
            "VESA_DSC_MODEL_ROOT must point to the extracted DSC_model_20211213 directory. "
            "Run tools/fetch_vesa_dsc_model.sh first.")
    endif()

    add_library(vesa_dsc_reference_c STATIC
        ${VESA_DSC_MODEL_ROOT}/source/dsc_codec.c
        ${VESA_DSC_MODEL_ROOT}/source/dsc_utils.c
        ${VESA_DSC_MODEL_ROOT}/source/fifo.c
        ${VESA_DSC_MODEL_ROOT}/source/logging.c
        ${VESA_DSC_MODEL_ROOT}/source/multiplex.c
        ${VESA_DSC_MODEL_ROOT}/source/utl.c
    )
    target_include_directories(vesa_dsc_reference_c PUBLIC ${VESA_DSC_MODEL_ROOT}/source)
    target_compile_definitions(vesa_dsc_reference_c PRIVATE _FILE_OFFSET_BITS=64)
    target_compile_options(vesa_dsc_reference_c PRIVATE -Wno-unused-result)
    target_link_libraries(vesa_dsc_reference_c PUBLIC m)

    add_library(vesa_reference_codec STATIC src/vesa_reference_codec.cpp)
    target_include_directories(vesa_reference_codec PUBLIC ${CMAKE_CURRENT_SOURCE_DIR}/include)
    target_link_libraries(vesa_reference_codec PUBLIC dsc_function_tlm vesa_dsc_reference_c)
    target_compile_options(vesa_reference_codec PRIVATE -Wall -Wextra -Wpedantic -Werror)

    add_executable(vesa_reference_codec_contract tests/vesa_reference_codec_contract.cpp)
    target_link_libraries(vesa_reference_codec_contract PRIVATE vesa_reference_codec)
    target_compile_options(vesa_reference_codec_contract PRIVATE -Wall -Wextra -Wpedantic -Werror)
endif()

enable_testing()
add_executable(dsc_function_tlm_contract tests/dsc_function_tlm_contract.cpp)
target_link_libraries(dsc_function_tlm_contract PRIVATE dsc_function_tlm)
target_compile_options(dsc_function_tlm_contract PRIVATE -Wall -Wextra -Wpedantic -Werror)
add_test(NAME dsc_function_tlm_contract COMMAND dsc_function_tlm_contract)

add_executable(layered_function_contract tests/layered_function_contract.cpp)
target_link_libraries(layered_function_contract PRIVATE dsc_function_tlm)
target_compile_options(layered_function_contract PRIVATE -Wall -Wextra -Wpedantic -Werror)
add_test(NAME layered_function_contract COMMAND layered_function_contract)
