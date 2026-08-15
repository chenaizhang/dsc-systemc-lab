#!/usr/bin/env bash
set -euo pipefail

script_dir=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
repository_root=$(cd "$script_dir/.." && pwd)
rtl_dir=${DSCFLOW_RTL_DIR:-$repository_root/inputs/private/rtl}
run_dir=${DSCFLOW_HYBRID_DIFFERENTIAL_RUN_DIR:-$repository_root/.work/runs/hybrid-differential}
model_dir=$run_dir/verilator
output_dir=$run_dir/outputs
golden_dir=$run_dir/golden
jobs=${DSCFLOW_BUILD_JOBS:-2}

if [[ "$(uname -m)" != "x86_64" ]]; then
    printf '正式验证只能在 x86_64 执行，当前为 %s\n' "$(uname -m)" >&2
    exit 2
fi
for command in verilator make c++ pkg-config python3 cmake; do
    command -v "$command" >/dev/null 2>&1 || { printf '缺少依赖：%s\n' "$command" >&2; exit 2; }
done
pkg-config --exists systemc || { printf 'pkg-config 找不到 SystemC\n' >&2; exit 2; }
test -f "$rtl_dir/surelog.f" || { printf '缺少私有 RTL filelist：%s\n' "$rtl_dir/surelog.f" >&2; exit 2; }

mkdir -p "$model_dir" "$output_dir" "$golden_dir"
DSCFLOW_RUN_DIR="$golden_dir" "$repository_root/models/function_tlm/run_x86_verify.sh"

filtered_filelist=$run_dir/verilator-reachable.f
{
    printf '%s\n' "$repository_root/models/cycle_systemc/rtl_shims/dsc_support_primitives.sv"
    grep -v -e '^dsc_support_primitives.sv$' -e '^dsce_quant.sv$' -e '^-timescale' "$rtl_dir/surelog.f"
} > "$filtered_filelist"

tops=(dsc_encoder dsce_apb dsce_command dsce_engine dsce_interrupt dsce_pps dsce_reset dsce_timers)
for top in "${tops[@]}"; do
    object_dir=$model_dir/$top
    mkdir -p "$object_dir"
    (cd "$rtl_dir" && verilator --cc --sc --timing --timescale 1ns/1ps -Wno-fatal \
        --top-module "$top" --prefix "V$top" --Mdir "$object_dir" \
        -f "$filtered_filelist") >"$object_dir/generate.log" 2>&1
    make -C "$object_dir" -f "V$top.mk" -j"$jobs" "V${top}__ALL.a" \
        >"$object_dir/build.log" 2>&1
done

verilator_root=$(verilator -V | sed -n 's/^ *VERILATOR_ROOT *= *//p' | head -n 1)
test -n "$verilator_root" || { printf '无法确定 VERILATOR_ROOT\n' >&2; exit 2; }

include_args=(-I"$repository_root/models/cycle_systemc/include" -I"$verilator_root/include")
library_args=()
for top in "${tops[@]}"; do
    include_args+=(-I"$model_dir/$top")
    library_args+=("$model_dir/$top/V${top}__ALL.a")
done

read -r -a systemc_cflags <<<"$(pkg-config --cflags systemc)"
read -r -a systemc_libs <<<"$(pkg-config --libs systemc)"
executable=$run_dir/hybrid_differential
if ! c++ -std=c++20 -O2 -Wall -Wextra -Wpedantic -DSC_DISABLE_API_VERSION_CHECK \
    "${include_args[@]}" "${systemc_cflags[@]}" \
    "$repository_root/models/cycle_systemc/tests/hybrid_differential.cpp" \
    "$verilator_root/include/verilated.cpp" \
    "$verilator_root/include/verilated_threads.cpp" \
    "$verilator_root/include/verilated_timing.cpp" \
    "${library_args[@]}" "${systemc_libs[@]}" -pthread -latomic -o "$executable" \
    >"$run_dir/compile.log" 2>&1; then
    tail -n 160 "$run_dir/compile.log" >&2
    exit 1
fi

"$executable" \
    "$golden_dir/deterministic_rgb.ppm" \
    "$golden_dir/deterministic_rgb.dsc" \
    "$output_dir" "$run_dir/runtime.json"

install -m 0644 "$output_dir/module_interface_trace.csv" \
    "$repository_root/evidence/results/hybrid_differential_module_interface_trace.csv"

python3 "$repository_root/tools/finalize_hybrid_differential_report.py" \
    --runtime "$run_dir/runtime.json" \
    --golden-report "$golden_dir/report.json" \
    --output-dir "$output_dir" \
    --report "$repository_root/evidence/results/hybrid_differential_x86.json"

printf 'DSC 混合差分验证完成：%s\n' "$repository_root/evidence/results/hybrid_differential_x86.json"
