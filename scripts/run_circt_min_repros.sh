#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
circt_root="${DSCFLOW_CIRCT_ROOT:-$HOME/.local/opt/circt-1.155.0}"
library_path="${DSCFLOW_CIRCT_LIBRARY_PATH:-$HOME/.local/opt/circt-1.155.0-deps/usr/lib/x86_64-linux-gnu}"
work_dir="${DSCFLOW_CIRCT_REPRO_WORK_DIR:-$repo_root/.work/circt-min-repros}"
evidence_dir="${DSCFLOW_CIRCT_REPRO_EVIDENCE_DIR:-$repo_root/evidence/results/circt_min_repros}"
frontend="$circt_root/bin/circt-verilog"
optimizer="$circt_root/bin/circt-opt"
translator="$circt_root/bin/circt-translate"

for tool in "$frontend" "$optimizer" "$translator"; do
  if [[ ! -x "$tool" ]]; then
    echo "error: missing CIRCT tool: $tool" >&2
    exit 2
  fi
done

mkdir -p "$work_dir" "$evidence_dir"
export LD_LIBRARY_PATH="$library_path${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"

source_file="$repo_root/tests/fixtures/circt/llhd_coroutine_task.sv"
core_ir="$work_dir/llhd_coroutine_task.hw.mlir"
conversion_log="$evidence_dir/llhd_coroutine_task.stderr.log"

"$frontend" --single-unit \
  --top llhd_coroutine_task \
  --ir-hw \
  "$source_file" \
  -o "$core_ir"

if ! grep -q 'llhd.coroutine.*llhd_coroutine_task_pkg::choose_min' "$core_ir"; then
  echo "error: frontend did not produce the expected llhd.coroutine" >&2
  exit 1
fi

set +e
"$optimizer" --convert-hw-to-systemc "$core_ir" -o "$work_dir/llhd_coroutine_task.systemc.mlir" \
  >"$evidence_dir/llhd_coroutine_task.stdout.log" 2>"$conversion_log"
status=$?
set -e

if [[ $status -eq 0 ]]; then
  echo "error: expected CIRCT 1.155.0 llhd.coroutine conversion failure did not occur" >&2
  exit 1
fi
if ! grep -q "failed to legalize operation 'llhd.coroutine'" "$conversion_log"; then
  echo "error: conversion failed for an unexpected reason" >&2
  sed -n '1,80p' "$conversion_log" >&2
  exit 1
fi

cp "$core_ir" "$evidence_dir/llhd_coroutine_task.hw.mlir"

control_source="$repo_root/tests/fixtures/circt/function_control.sv"
control_core="$work_dir/function_control.hw.mlir"
control_systemc="$work_dir/function_control.systemc.mlir"
control_export_log="$evidence_dir/function_control_export.stderr.log"

"$frontend" --single-unit \
  --top function_control \
  --ir-hw \
  "$control_source" \
  -o "$control_core"
"$optimizer" --convert-hw-to-systemc "$control_core" -o "$control_systemc"

set +e
"$translator" --export-systemc "$control_systemc" \
  >"$evidence_dir/function_control.partial.cpp" 2>"$control_export_log"
control_status=$?
set -e

if [[ $control_status -eq 0 ]]; then
  echo "error: expected CIRCT 1.155.0 SystemC emission failure did not occur" >&2
  exit 1
fi
for pattern in "systemc.convert" "comb.icmp" "comb.mux"; do
  if ! grep -q "no emission pattern found for '$pattern'" "$control_export_log"; then
    echo "error: missing expected emission failure for $pattern" >&2
    exit 1
  fi
done

cp "$control_core" "$evidence_dir/function_control.hw.mlir"
cp "$control_systemc" "$evidence_dir/function_control.systemc.mlir"
echo "CIRCT minimal reproductions verified: task conversion and function emission gaps are isolated"
