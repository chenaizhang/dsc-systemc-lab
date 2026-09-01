#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
circt_root="${DSCFLOW_CIRCT_ROOT:-$HOME/.local/opt/circt-systemc-fork}"
library_path="${DSCFLOW_CIRCT_LIBRARY_PATH:-$circt_root/lib}"
work_dir="${DSCFLOW_HIERARCHY_REPRO_WORK_DIR:-$repo_root/.work/circt-hierarchy-repro}"
frontend="$circt_root/bin/circt-verilog"

[[ -x "$frontend" ]] || { echo "error: missing CIRCT frontend: $frontend" >&2; exit 2; }
mkdir -p "$work_dir"
export LD_LIBRARY_PATH="$library_path${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"

core_ir="$work_dir/hierarchy_top.hw.mlir"
"$frontend" --single-unit --top hierarchy_top --ir-hw \
  "$repo_root/tests/fixtures/circt/hierarchy_peeling.sv" -o "$core_ir"

for depth in 0 1 2; do
  "$repo_root/scripts/run_circt_hierarchy_peeling.sh" \
    "$core_ir" hierarchy_top "$depth" "$work_dir/depth-$depth"
done
