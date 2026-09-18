#!/usr/bin/env bash
set -euo pipefail

repository_root=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
cd "$repository_root"

if [[ $(uname -m) != x86_64 ]]; then
    printf 'This verification must run on Linux x86_64.\n' >&2
    exit 2
fi
for command in python3 c++ pkg-config timeout sha256sum; do
    command -v "$command" >/dev/null 2>&1 || {
        printf 'Missing tool: %s\n' "$command" >&2
        exit 2
    }
done
pkg-config --exists systemc || { printf 'SystemC pkg-config entry is missing.\n' >&2; exit 2; }

: "${DSCFLOW_CIRCT_ROOT:?Set DSCFLOW_CIRCT_ROOT to the CIRCT release directory}"
rtl_dir=${DSCFLOW_PRIVATE_RTL_DIR:-$repository_root/inputs/private/rtl}
reference_root=${DSCFLOW_VESA_ROOT:-$repository_root/third_party/vesa-dsc-model-20211213/DSC_model_20211213}
adapter_test=${DSCFLOW_VESA_ADAPTER_TEST:-$repository_root/.work/build/function-tlm/vesa_reference_codec_contract}
output_dir=${DSCFLOW_NATIVE_OUTPUT_DIR:-$repository_root/.work/runs/native-image-differential}
width=${DSCFLOW_NATIVE_WIDTH:-96}
height=${DSCFLOW_NATIVE_HEIGHT:-16}
slice_width=${DSCFLOW_NATIVE_SLICE_WIDTH:-96}
simulation_timeout=${DSCFLOW_NATIVE_TIMEOUT:-900}

for required in "$reference_root/source/dsc" "$adapter_test" \
    "$DSCFLOW_CIRCT_ROOT/bin/circt-verilog" "$DSCFLOW_CIRCT_ROOT/bin/circt-opt"; do
    if [[ ! -e $required ]]; then
        printf 'Missing prerequisite: %s\n' "$required" >&2
        exit 2
    fi
done
mkdir -p "$output_dir"
output_dir=$(cd "$output_dir" && pwd)
export DSCFLOW_CIRCT_LIBRARY_PATH=${DSCFLOW_CIRCT_LIBRARY_PATH:-$DSCFLOW_CIRCT_ROOT/lib}
export DSCFLOW_SYSTEMC_MODE=behavior

python3 tools/run_dsc_reference_differential.py \
    --model-root "$reference_root" --adapter-test "$adapter_test" \
    --work-dir "$output_dir/reference" --report "$output_dir/reference/report.json" \
    --width "$width" --height "$height" --slice-width "$slice_width" \
    >"$output_dir/reference.log" 2>&1

sources=("$repository_root/models/cycle_systemc/rtl_shims/dsc_support_primitives.sv")
input_hw_ir=${DSCFLOW_NATIVE_HW_IR:-$output_dir/dsc_encoder.hw.mlir}
if [[ -n ${DSCFLOW_NATIVE_HW_IR:-} ]]; then
    test -f "$input_hw_ir" || { printf 'Missing HW IR: %s\n' "$input_hw_ir" >&2; exit 2; }
else
    for required in "$rtl_dir/surelog.f" "${sources[0]}"; do
        test -f "$required" || { printf 'Missing RTL input: %s\n' "$required" >&2; exit 2; }
    done
    while IFS= read -r source; do
        case $source in
            +incdir+*|-timescale*|dsc_support_primitives.sv|dsce_quant.sv) ;;
            *.sv) sources+=("$source") ;;
        esac
    done <"$rtl_dir/surelog.f"
    (
        cd "$rtl_dir"
        "$DSCFLOW_CIRCT_ROOT/bin/circt-verilog" --single-unit --top dsc_encoder \
            --ir-hw --timescale 1ns/1ps -I . "${sources[@]}" \
            -o "$input_hw_ir"
    ) >"$output_dir/frontend.log" 2>&1
fi

scripts/run_circt_hierarchy_peeling.sh \
    "$input_hw_ir" dsc_encoder 6 "$output_dir/depth-6" \
    >"$output_dir/conversion.log" 2>&1
sha256sum "$input_hw_ir" "$output_dir/depth-6/depth_6.systemc.hpp" \
    >"$output_dir/artifact-sha256.txt"

c++ -std=c++17 -O1 -I"$output_dir/depth-6" \
    models/cycle_systemc/tests/native_image_differential.cpp \
    -o "$output_dir/native_image_differential" \
    $(pkg-config --cflags --libs systemc) \
    >"$output_dir/compile.log" 2>&1

set +e
timeout "${simulation_timeout}s" "$output_dir/native_image_differential" \
    "$output_dir/reference/deterministic_rgb.ppm" \
    "$output_dir/reference/deterministic_rgb.dsc" \
    "$output_dir/native_payload.bin" \
    >"$output_dir/runtime.log" 2>&1
result=$?
set -e
printf 'Simulation exit=%s; logs and output: %s\n' "$result" "$output_dir"
tail -n 20 "$output_dir/runtime.log"
exit "$result"
