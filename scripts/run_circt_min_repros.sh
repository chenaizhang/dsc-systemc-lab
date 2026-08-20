#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
circt_root="${DSCFLOW_CIRCT_ROOT:-$HOME/.local/opt/circt-systemc-fork}"
library_path="${DSCFLOW_CIRCT_LIBRARY_PATH:-$circt_root/lib}"
work_dir="${DSCFLOW_CIRCT_REPRO_WORK_DIR:-$repo_root/.work/circt-min-repros}"
evidence_dir="${DSCFLOW_CIRCT_REPRO_EVIDENCE_DIR:-$repo_root/evidence/results/circt_min_repros}"
frontend="$circt_root/bin/circt-verilog"
optimizer="$circt_root/bin/circt-opt"
translator="$circt_root/bin/circt-translate"
cxx="${CXX:-c++}"

for tool in "$frontend" "$optimizer" "$translator"; do
  if [[ ! -x "$tool" ]]; then
    echo "error: missing CIRCT tool: $tool" >&2
    exit 2
  fi
done

mkdir -p "$work_dir" "$evidence_dir"
export LD_LIBRARY_PATH="$library_path${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"

for case_name in llhd_coroutine_task function_control; do
  source_file="$repo_root/tests/fixtures/circt/$case_name.sv"
  core_ir="$work_dir/$case_name.hw.mlir"
  llhd_core_ir="$work_dir/$case_name.llhd-core.mlir"
  llhd_lowered_ir="$work_dir/$case_name.llhd-lowered.mlir"
  structure_ir="$work_dir/$case_name.structure.systemc.mlir"
  structure_cpp="$work_dir/$case_name.structure.systemc.hpp"

  "$frontend" --single-unit --top "$case_name" --ir-hw "$source_file" -o "$core_ir"
  "$optimizer" --convert-hw-to-systemc="structure-only=true" \
    "$core_ir" -o "$structure_ir"
  "$translator" --export-systemc "$structure_ir" -o "$structure_cpp"
  "$cxx" -std=c++17 -x c++ -fsyntax-only \
    $(pkg-config --cflags systemc) "$structure_cpp"

  "$optimizer" --pass-pipeline='builtin.module(hw.module(llhd-wrap-procedural-ops),llhd-inline-calls,llhd-inline-suspend-free-coroutines,symbol-dce,hw.module(sroa,llhd-mem2reg,llhd-hoist-signals,llhd-deseq,llhd-lower-processes,cse,canonicalize,llhd-unroll-loops,cse,canonicalize,llhd-remove-control-flow,cse,canonicalize,map-arith-to-comb{enable-best-effort-lowering=true},llhd-combine-drives,llhd-sig2reg,cse,canonicalize))' \
    "$core_ir" -o "$llhd_core_ir"
  "$optimizer" --mlir-disable-threading --llhd-lower-timed-processes \
    "$llhd_core_ir" -o "$llhd_lowered_ir"

  set +e
  "$optimizer" --convert-hw-to-systemc "$llhd_lowered_ir" \
    -o "$work_dir/$case_name.full.systemc.mlir" \
    >"$evidence_dir/$case_name.full.stdout.log" \
    2>"$evidence_dir/$case_name.full.stderr.log"
  full_status=$?
  set -e
  printf '%s\n' "$full_status" >"$evidence_dir/$case_name.full.status"
  cp "$core_ir" "$evidence_dir/$case_name.hw.mlir"
  cp "$llhd_lowered_ir" "$evidence_dir/$case_name.llhd-lowered.mlir"
  cp "$structure_ir" "$evidence_dir/$case_name.structure.systemc.mlir"
done

echo "CIRCT HW-only probes compile; full Comb/Seq status is preserved as evidence"
