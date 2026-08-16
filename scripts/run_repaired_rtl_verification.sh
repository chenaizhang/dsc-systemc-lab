#!/usr/bin/env bash
set -euo pipefail

script_dir=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
repository_root=$(cd "$script_dir/.." && pwd)

DSCFLOW_APPLY_RTL_REPAIR=1 \
# Default to the three independently demonstrated handshake/boundary fixes.
# The reconstructed line-last chain remains opt-in because its differential
# experiment does not yet satisfy the VESA golden gate.
DSCFLOW_RTL_OVERLAYS=${DSCFLOW_RTL_OVERLAYS:-bypass,format-buffer,slice-mux} \
DSCFLOW_DSC_CLOCK_NUMERATOR=${DSCFLOW_DSC_CLOCK_NUMERATOR:-3} \
DSCFLOW_DSC_CLOCK_DENOMINATOR=${DSCFLOW_DSC_CLOCK_DENOMINATOR:-1} \
DSCFLOW_HYBRID_DIFFERENTIAL_RUN_DIR=${DSCFLOW_REPAIRED_RTL_RUN_DIR:-$repository_root/.work/runs/repaired-rtl-differential} \
DSCFLOW_HYBRID_REPORT=$repository_root/evidence/results/repaired_rtl_differential_x86.json \
DSCFLOW_INTERFACE_TRACE_EVIDENCE=$repository_root/evidence/results/repaired_rtl_module_interface_trace.csv \
DSCFLOW_ENGINE_TRACE_EVIDENCE=$repository_root/evidence/results/repaired_rtl_engine_boundary_trace.csv \
DSCFLOW_ENGINE_DSC_TRACE_EVIDENCE=$repository_root/evidence/results/repaired_rtl_engine_dsc_boundary_trace.csv \
    "$script_dir/run_hybrid_differential_verification.sh"
