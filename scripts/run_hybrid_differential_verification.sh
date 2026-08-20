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
dsc_clock_numerator=${DSCFLOW_DSC_CLOCK_NUMERATOR:-3}
dsc_clock_denominator=${DSCFLOW_DSC_CLOCK_DENOMINATOR:-1}
apply_rtl_repair=${DSCFLOW_APPLY_RTL_REPAIR:-0}
rtl_overlays=${DSCFLOW_RTL_OVERLAYS:-}
report_path=${DSCFLOW_HYBRID_REPORT:-$repository_root/evidence/results/hybrid_differential_x86.json}
interface_trace_evidence=${DSCFLOW_INTERFACE_TRACE_EVIDENCE:-$repository_root/evidence/results/hybrid_differential_module_interface_trace.csv}
engine_trace_evidence=${DSCFLOW_ENGINE_TRACE_EVIDENCE:-$repository_root/evidence/results/hybrid_differential_engine_boundary_trace.csv}
engine_dsc_trace_evidence=${DSCFLOW_ENGINE_DSC_TRACE_EVIDENCE:-$repository_root/evidence/results/hybrid_differential_engine_dsc_boundary_trace.csv}

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

if [[ -z "$rtl_overlays" && "$apply_rtl_repair" == "1" ]]; then
    rtl_overlays=bypass,format-buffer,slice-mux
fi
overlay_enabled() {
    [[ ",$rtl_overlays," == *",$1,"* ]]
}

filtered_filelist=$run_dir/verilator-reachable.f
{
    printf '%s\n' "$repository_root/models/cycle_systemc/rtl_shims/dsc_support_primitives.sv"
    if overlay_enabled bypass; then
        bypass_overlay=$run_dir/rtl-overlay/dsce_bypass.sv
        python3 "$repository_root/tools/prepare_rtl_overlay.py" \
            --repair bypass --input "$rtl_dir/dsce_bypass.sv" --output "$bypass_overlay"
    fi
    if overlay_enabled format-buffer; then
        format_buffer_overlay=$run_dir/rtl-overlay/dsce_format_buffer.sv
        python3 "$repository_root/tools/prepare_rtl_overlay.py" \
            --repair format-buffer --input "$rtl_dir/dsce_format_buffer.sv" --output "$format_buffer_overlay"
    fi
    if overlay_enabled slice-mux; then
        slice_mux_overlay=$run_dir/rtl-overlay/dsce_slice_mux.sv
        python3 "$repository_root/tools/prepare_rtl_overlay.py" \
            --repair slice-mux --input "$rtl_dir/dsce_slice_mux.sv" --output "$slice_mux_overlay"
    fi
    if overlay_enabled muxword-contract; then
        muxword_overlay=$run_dir/rtl-overlay/dsce_muxword.sv
        python3 "$repository_root/tools/prepare_rtl_overlay.py" \
            --repair muxword-contract --input "$rtl_dir/dsce_muxword.sv" --output "$muxword_overlay"
    fi
    if overlay_enabled muxword-flush; then
        muxword_overlay=$run_dir/rtl-overlay/dsce_muxword.sv
        python3 "$repository_root/tools/prepare_rtl_overlay.py" \
            --repair muxword-flush --input "$rtl_dir/dsce_muxword.sv" --output "$muxword_overlay"
    fi
    if overlay_enabled muxword-flush-dedup; then
        muxword_overlay=${muxword_overlay:-$run_dir/rtl-overlay/dsce_muxword.sv}
        muxword_input=$rtl_dir/dsce_muxword.sv
        if overlay_enabled muxword-contract; then
        muxword_overlay=$run_dir/rtl-overlay/dsce_muxword.sv
        python3 "$repository_root/tools/prepare_rtl_overlay.py" \
            --repair muxword-contract --input "$rtl_dir/dsce_muxword.sv" --output "$muxword_overlay"
    fi
    if overlay_enabled muxword-flush; then
            muxword_input=$muxword_overlay
        fi
        python3 "$repository_root/tools/prepare_rtl_overlay.py" \
            --repair muxword-flush-dedup --input "$muxword_input" --output "$muxword_overlay.next"
        mv "$muxword_overlay.next" "$muxword_overlay"
    fi
    if overlay_enabled muxword-last; then
        muxword_overlay=${muxword_overlay:-$run_dir/rtl-overlay/dsce_muxword.sv}
        muxword_input=$rtl_dir/dsce_muxword.sv
        if overlay_enabled muxword-contract; then
        muxword_overlay=$run_dir/rtl-overlay/dsce_muxword.sv
        python3 "$repository_root/tools/prepare_rtl_overlay.py" \
            --repair muxword-contract --input "$rtl_dir/dsce_muxword.sv" --output "$muxword_overlay"
    fi
    if overlay_enabled muxword-flush; then
            muxword_input=$muxword_overlay
        fi
        python3 "$repository_root/tools/prepare_rtl_overlay.py" \
            --repair muxword-last --input "$muxword_input" --output "$muxword_overlay.next"
        mv "$muxword_overlay.next" "$muxword_overlay"
    fi
    if overlay_enabled format-last-wiring; then
        format_overlay=$run_dir/rtl-overlay/dsce_format.sv
        python3 "$repository_root/tools/prepare_rtl_overlay.py" \
            --repair format-last-wiring --input "$rtl_dir/dsce_format.sv" --output "$format_overlay"
    fi
    if overlay_enabled stream-fifo-last; then
        stream_fifo_overlay=$run_dir/rtl-overlay/dsce_stream_fifo.sv
        python3 "$repository_root/tools/prepare_rtl_overlay.py" \
            --repair stream-fifo-last --input "$rtl_dir/dsce_stream_fifo.sv" --output "$stream_fifo_overlay"
    fi
    if overlay_enabled stream-builder-last; then
        stream_builder_overlay=$run_dir/rtl-overlay/dsce_stream_builder.sv
        python3 "$repository_root/tools/prepare_rtl_overlay.py" \
            --repair stream-builder-last --input "$rtl_dir/dsce_stream_builder.sv" --output "$stream_builder_overlay"
    fi
    if overlay_enabled fifo-input-ready; then
        stream_fifo_overlay=${stream_fifo_overlay:-$run_dir/rtl-overlay/dsce_stream_fifo.sv}
        fifo_input=$rtl_dir/dsce_stream_fifo.sv
        if overlay_enabled stream-fifo-last; then
            fifo_input=$stream_fifo_overlay
        fi
        python3 "$repository_root/tools/prepare_rtl_overlay.py" \
            --repair fifo-input-ready --input "$fifo_input" --output "$stream_fifo_overlay.next"
        mv "$stream_fifo_overlay.next" "$stream_fifo_overlay"
    fi
    if overlay_enabled muxword-backpressure; then
        muxword_overlay=${muxword_overlay:-$run_dir/rtl-overlay/dsce_muxword.sv}
        muxword_input=$rtl_dir/dsce_muxword.sv
        if overlay_enabled muxword-flush || overlay_enabled muxword-last; then
            muxword_input=$muxword_overlay
        fi
        python3 "$repository_root/tools/prepare_rtl_overlay.py" \
            --repair muxword-backpressure --input "$muxword_input" --output "$muxword_overlay.next"
        mv "$muxword_overlay.next" "$muxword_overlay"
    fi
    if overlay_enabled builder-accept-passthrough; then
        stream_builder_overlay=${stream_builder_overlay:-$run_dir/rtl-overlay/dsce_stream_builder.sv}
        builder_input=$rtl_dir/dsce_stream_builder.sv
        if overlay_enabled stream-builder-last; then
            builder_input=$stream_builder_overlay
        fi
        python3 "$repository_root/tools/prepare_rtl_overlay.py" \
            --repair builder-accept-passthrough --input "$builder_input" --output "$stream_builder_overlay.next"
        mv "$stream_builder_overlay.next" "$stream_builder_overlay"
    fi
    if overlay_enabled format-backpressure-wiring; then
        format_overlay=${format_overlay:-$run_dir/rtl-overlay/dsce_format.sv}
        format_input=$rtl_dir/dsce_format.sv
        if overlay_enabled format-last-wiring; then
            format_input=$format_overlay
        fi
        python3 "$repository_root/tools/prepare_rtl_overlay.py" \
            --repair format-backpressure-wiring --input "$format_input" --output "$format_overlay.next"
        mv "$format_overlay.next" "$format_overlay"
    fi
    while IFS= read -r source; do
        case "$source" in
            dsc_support_primitives.sv|dsce_quant.sv|-timescale*) continue ;;
            dsce_bypass.sv)
                if overlay_enabled bypass; then
                    printf '%s\n' "$bypass_overlay"
                else
                    printf '%s\n' "$source"
                fi
                ;;
            dsce_format_buffer.sv)
                if overlay_enabled format-buffer; then
                    printf '%s\n' "$format_buffer_overlay"
                else
                    printf '%s\n' "$source"
                fi
                ;;
            dsce_slice_mux.sv)
                if overlay_enabled slice-mux; then
                    printf '%s\n' "$slice_mux_overlay"
                else
                    printf '%s\n' "$source"
                fi
                ;;
            dsce_muxword.sv)
                if overlay_enabled muxword-contract || overlay_enabled muxword-flush || overlay_enabled muxword-flush-dedup || overlay_enabled muxword-last || overlay_enabled muxword-backpressure; then
                    printf '%s\n' "$muxword_overlay"
                else
                    printf '%s\n' "$source"
                fi
                ;;
            dsce_format.sv)
                if overlay_enabled format-last-wiring || overlay_enabled format-backpressure-wiring; then
                    printf '%s\n' "$format_overlay"
                else
                    printf '%s\n' "$source"
                fi
                ;;
            dsce_stream_fifo.sv)
                if overlay_enabled stream-fifo-last || overlay_enabled fifo-input-ready; then
                    printf '%s\n' "$stream_fifo_overlay"
                else
                    printf '%s\n' "$source"
                fi
                ;;
            dsce_stream_builder.sv)
                if overlay_enabled stream-builder-last || overlay_enabled builder-accept-passthrough; then
                    printf '%s\n' "$stream_builder_overlay"
                else
                    printf '%s\n' "$source"
                fi
                ;;
            *) printf '%s\n' "$source" ;;
        esac
    done < "$rtl_dir/surelog.f"
} > "$filtered_filelist"

tops=(dsc_encoder dsce_apb dsce_command dsce_engine dsce_interrupt dsce_pps dsce_reset dsce_timers)
for top in "${tops[@]}"; do
    object_dir=$model_dir/$top
    mkdir -p "$object_dir"
    (cd "$rtl_dir" && verilator --cc --sc --timing --public-flat-rw --timescale 1ns/1ps -Wno-fatal \
        --top-module "$top" --prefix "V$top" --Mdir "$object_dir" \
        -f "$filtered_filelist") >"$object_dir/generate.log" 2>&1
    make -C "$object_dir" -f "V$top.mk" -j"$jobs" "V${top}__ALL.a" \
        >"$object_dir/build.log" 2>&1
done

verilator_root=$(verilator -V | sed -n 's/^ *VERILATOR_ROOT *= *//p' | head -n 1)
test -n "$verilator_root" || { printf '无法确定 VERILATOR_ROOT\n' >&2; exit 2; }

include_args=(-I"$repository_root/models/cycle_systemc/include" -I"$verilator_root/include" -I"$verilator_root/include/vltstd")
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
    "$output_dir" "$run_dir/runtime.json" \
    "$dsc_clock_numerator" "$dsc_clock_denominator"

install -m 0644 "$output_dir/module_interface_trace.csv" \
    "$interface_trace_evidence"
install -m 0644 "$output_dir/engine_boundary_trace.csv" \
    "$engine_trace_evidence"
install -m 0644 "$output_dir/engine_dsc_boundary_trace.csv" \
    "$engine_dsc_trace_evidence"

python3 "$repository_root/tools/finalize_hybrid_differential_report.py" \
    --runtime "$run_dir/runtime.json" \
    --golden-report "$golden_dir/report.json" \
    --output-dir "$output_dir" \
    --report "$report_path"

printf 'DSC 混合差分验证完成：%s\n' "$report_path"
