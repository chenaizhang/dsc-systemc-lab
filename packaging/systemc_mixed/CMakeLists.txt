cmake_minimum_required(VERSION 3.20)
project(portable_systemc_mixed_model LANGUAGES CXX)

include(CTest)

set(CMAKE_CXX_STANDARD 20)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)

find_program(VERILATOR_EXECUTABLE NAMES verilator REQUIRED)
execute_process(
  COMMAND "${VERILATOR_EXECUTABLE}" -V
  OUTPUT_VARIABLE verilator_version_output
  RESULT_VARIABLE verilator_version_status
)
if(NOT verilator_version_status EQUAL 0)
  message(FATAL_ERROR "verilator -V failed")
endif()
string(
  REGEX MATCH "VERILATOR_ROOT[ \t]*=[ \t]*([^\n\r]+)"
  _verilator_root_match
  "${verilator_version_output}"
)
string(STRIP "${CMAKE_MATCH_1}" detected_verilator_root)
find_package(
  verilator CONFIG REQUIRED
  HINTS $ENV{VERILATOR_ROOT} "${detected_verilator_root}"
)

find_package(SystemCLanguage CONFIG QUIET)
if(TARGET SystemC::systemc)
  set(systemc_target SystemC::systemc)
else()
  find_package(PkgConfig REQUIRED)
  pkg_check_modules(SYSTEMC REQUIRED IMPORTED_TARGET systemc)
  set(systemc_target PkgConfig::SYSTEMC)
endif()

set(generated_dir "${CMAKE_CURRENT_SOURCE_DIR}/generated")
set(mixed_header "${generated_dir}/mixed_systemc.hpp")
set(module_manifest "${generated_dir}/interop_modules.cmake")

foreach(required_file IN ITEMS "${mixed_header}" "${module_manifest}")
  if(NOT EXISTS "${required_file}")
    message(FATAL_ERROR "Missing generated handoff input: ${required_file}")
  endif()
endforeach()

include("${module_manifest}")
if(NOT INTEROP_MODULES)
  message(FATAL_ERROR "INTEROP_MODULES is empty")
endif()

add_executable(mixed_systemc_smoke tests/mixed_systemc_smoke.cpp)
target_include_directories(mixed_systemc_smoke PRIVATE "${generated_dir}")
target_link_libraries(mixed_systemc_smoke PRIVATE "${systemc_target}")
target_compile_definitions(mixed_systemc_smoke PRIVATE SC_DISABLE_API_VERSION_CHECK)
# This target compiles a large generated header to verify ABI, linkage and
# runtime construction. Optimisation and debug information provide no extra
# coverage here, but substantially increase build time and compiler memory.
if(CMAKE_CXX_COMPILER_ID MATCHES "GNU|Clang")
  target_compile_options(mixed_systemc_smoke PRIVATE -O0 -g0)
endif()

foreach(module_name IN LISTS INTEROP_MODULES)
  string(MAKE_C_IDENTIFIER "${module_name}" module_identifier)
  set(flattened_rtl "${generated_dir}/interop_${module_name}.sv")
  if(NOT EXISTS "${flattened_rtl}")
    message(FATAL_ERROR "Missing flattened RTL for ${module_name}: ${flattened_rtl}")
  endif()
  verilate(
    mixed_systemc_smoke
    SOURCES "${flattened_rtl}"
    TOP_MODULE "${module_name}"
    PREFIX "V${module_identifier}"
    DIRECTORY "${CMAKE_CURRENT_BINARY_DIR}/verilated/${module_identifier}"
    VERILATOR_ARGS --timing -Wno-fatal
  )
endforeach()

add_test(NAME mixed-systemc-smoke COMMAND mixed_systemc_smoke)
set_tests_properties(
  mixed-systemc-smoke
  PROPERTIES PASS_REGULAR_EXPRESSION "MIXED_SYSTEMC_SMOKE=PASS"
)

set(cdc_object_dir "${CMAKE_CURRENT_BINARY_DIR}/cdc_shim")
set(cdc_executable "${cdc_object_dir}/Vcdc_shim_tb")
add_custom_command(
  OUTPUT "${cdc_executable}"
  COMMAND
    "${VERILATOR_BIN}" --binary --timing -Wno-fatal
    --top-module cdc_shim_tb
    --Mdir "${cdc_object_dir}"
    "${CMAKE_CURRENT_SOURCE_DIR}/rtl_shims/dsc_support_primitives.sv"
    "${CMAKE_CURRENT_SOURCE_DIR}/tests/cdc_shim_tb.sv"
  DEPENDS
    rtl_shims/dsc_support_primitives.sv
    tests/cdc_shim_tb.sv
  VERBATIM
)
add_custom_target(cdc_shim_model ALL DEPENDS "${cdc_executable}")
add_test(NAME cdc-shim COMMAND "${cdc_executable}")
set_tests_properties(cdc-shim PROPERTIES PASS_REGULAR_EXPRESSION "CDC_SHIM_TEST=PASS")
