#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
run_root="${DSCFLOW_LAYERED_RUN_ROOT:-$repo_root/.work/runs/layered-equivalence}"
staged_root="${DSCFLOW_STAGED_RUN_ROOT:-$repo_root/.work/runs/staged-circt}"
run_id="${DSCFLOW_RUN_ID:-x86-current}"
input_root="${VERILOG_DSC_ROOT:-$repo_root/inputs/private/rtl}"
circt_root="${DSCFLOW_CIRCT_ROOT:-$HOME/.local/opt/circt-systemc-fork}"
circt_library_path="${DSCFLOW_CIRCT_LIBRARY_PATH:-$circt_root/lib}"

cd "$repo_root"

dscflow layered prepare \
  --config configs/layered_equivalence.json \
  --output-dir "$run_root"

dscflow uhdm-systemc verify \
  --config configs/uhdm_agent.json \
  --run-dir "$run_root" \
  --candidate-dir "$run_root/candidate"

dscflow circt run \
  --config configs/staged_circt.json \
  --input-root "$input_root" \
  --output-root "$staged_root" \
  --run-id "$run_id" \
  --circt-root "$circt_root" \
  --circt-library-path "$circt_library_path"

python3 tools/finalize_layered_systemc_report.py \
  --staged-report "$staged_root/$run_id/report.json" \
  --uhdm-report "$run_root/verification/report.json" \
  --layer-plan "$run_root/layered_equivalence_plan.json" \
  --output evidence/results/layered_systemc_equivalence_x86.json

echo "Layered SystemC structure and equivalence gates completed"
