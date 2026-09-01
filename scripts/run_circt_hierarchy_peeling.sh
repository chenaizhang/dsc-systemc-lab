#!/usr/bin/env bash
set -euo pipefail

if [[ $# -lt 4 || $# -gt 5 ]]; then
  echo "用法: $0 <core.mlir> <top> <max-depth> <output-dir> [uhdm-hierarchy.json]" >&2
  exit 2
fi

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
core_ir=$1
top=$2
max_depth=$3
output_dir=$4
uhdm_json=${5:-}
circt_root="${DSCFLOW_CIRCT_ROOT:-$HOME/.local/opt/circt-systemc-fork}"
library_path="${DSCFLOW_CIRCT_LIBRARY_PATH:-$circt_root/lib}"
optimizer="$circt_root/bin/circt-opt"
translator="$circt_root/bin/circt-translate"
cxx="${CXX:-c++}"

for input in "$core_ir"; do
  [[ -f "$input" ]] || { echo "error: missing input: $input" >&2; exit 2; }
done
for tool in "$optimizer" "$translator" "$cxx"; do
  command -v "$tool" >/dev/null 2>&1 || [[ -x "$tool" ]] || {
    echo "error: missing tool: $tool" >&2
    exit 2
  }
done
if [[ -n "$uhdm_json" && ! -f "$uhdm_json" ]]; then
  echo "error: missing UHDM hierarchy: $uhdm_json" >&2
  exit 2
fi

mkdir -p "$output_dir"
export LD_LIBRARY_PATH="$library_path${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"

slice_ir="$output_dir/depth_${max_depth}.hw.mlir"
manifest="$output_dir/depth_${max_depth}.manifest.json"
systemc_ir="$output_dir/depth_${max_depth}.systemc.mlir"
systemc_cpp="$output_dir/depth_${max_depth}.systemc.hpp"
report="$output_dir/depth_${max_depth}.verification.json"

"$optimizer" \
  --hw-extract-hierarchy-slice="top=$top max-depth=$max_depth manifest=$manifest" \
  "$core_ir" -o "$slice_ir"
"$optimizer" --convert-hw-to-systemc="structure-only=true" \
  "$slice_ir" -o "$systemc_ir"
"$optimizer" "$systemc_ir" -o /dev/null
"$translator" --export-systemc "$systemc_ir" -o "$systemc_cpp"
"$cxx" -std=c++17 -x c++ -fsyntax-only \
  $(pkg-config --cflags systemc) "$systemc_cpp"

verify_args=(
  --manifest "$manifest"
  --hw-mlir "$slice_ir"
  --systemc "$systemc_cpp"
  --report "$report"
)
if [[ -n "$uhdm_json" ]]; then
  verify_args+=(--uhdm-json "$uhdm_json")
fi
python3 "$repo_root/tools/verify_circt_hierarchy_slice.py" "${verify_args[@]}"
