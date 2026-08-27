#!/usr/bin/env bash
set -euo pipefail

if [[ $# -lt 3 || $# -gt 7 ]]; then
  echo "用法: $0 <私有RTL目录> <CIRCT构建目录> <全新工作目录> [SystemC CMake目录] [顶层] [interop模块CSV] [配置文件]" >&2
  exit 2
fi

rtl_root=$1
circt_build=$2
work_root=$3
systemc_cmake_root=${4:-}
top_module=${5:-dsce_engine}
module_csv=${6:-dsce_pack,dsce_partition,dsce_slice,dsce_slice_mux,dsce_bypass}
config_path=${7:-}
script_dir=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
repository_root=$(cd "$script_dir/.." && pwd)
if [[ -z "$config_path" ]]; then
  config_path="$repository_root/configs/portable_mixed_dsc.json"
fi

if [[ "$(uname -m)" != "x86_64" ]]; then
  echo "正式混合集成验证只能在 x86_64 Linux 执行。" >&2
  exit 2
fi
if [[ -e "$work_root" ]]; then
  echo "工作目录已存在，必须使用全新目录: $work_root" >&2
  exit 2
fi
for required_path in \
  "$rtl_root/surelog.f" \
  "$circt_build/bin/circt-opt" \
  "$circt_build/bin/circt-verilog" \
  "$circt_build/bin/circt-translate"; do
  if [[ ! -e "$required_path" ]]; then
    echo "缺少输入或工具: $required_path" >&2
    exit 2
  fi
done

mkdir -p "$work_root/pipeline"
export LD_LIBRARY_PATH="$circt_build/lib${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"

set +e
PYTHONPATH="$repository_root/src${PYTHONPATH:+:$PYTHONPATH}" \
python3 -m dscflow circt run \
  --repo-root "$repository_root" \
  --config "$config_path" \
  --input-root "$rtl_root" \
  --output-root "$work_root/pipeline" \
  --run-id frontend \
  --circt-root "$circt_build" \
  --circt-library-path "$circt_build/lib"
frontend_status=$?
set -e

stage_dir=$work_root/pipeline/frontend/02_circt
lowered_ir=$stage_dir/$top_module.llhd-lowered.mlir
prepared_ir=$work_root/$top_module.prepared.mlir
mixed_ir=$work_root/$top_module.mixed.systemc.mlir
mixed_header=$work_root/$top_module.mixed.systemc.hpp

# The diagnostic workflow deliberately reports the unrelated, uninstantiated
# dsce_quant source error, so its aggregate exit status may be non-zero even
# when the reachable top Core IR was produced successfully.
if [[ ! -s "$lowered_ir" ]]; then
  echo "$top_module 可达设计未生成 LLHD-lowered Core IR (dscflow=$frontend_status)" >&2
  exit 1
fi
if ! rg -q "hw\.module (private )?@${top_module}[ (]" "$lowered_ir"; then
  echo "Core IR 中没有请求的顶层 $top_module；拒绝把子模块结果误标为完整 top" >&2
  exit 1
fi

"$circt_build/bin/circt-opt" \
  --hw-flatten-io="flatten-arrays=true join-char=_" \
  --hw-aggregate-to-comb \
  --hw-convert-bitcasts \
  --hw-aggregate-to-comb \
  "$lowered_ir" -o "$prepared_ir"

"$circt_build/bin/circt-opt" --verify-each=false \
  --systemc-wrap-verilated-instances="modules=$module_csv" \
  --symbol-dce \
  --convert-hw-to-systemc="prepared-input=true" \
  --systemc-lower-instance-interop \
  --systemc-lower-container-interop \
  "$prepared_ir" -o "$mixed_ir"

"$circt_build/bin/circt-opt" "$mixed_ir" -o /dev/null
"$circt_build/bin/circt-translate" --export-systemc \
  "$mixed_ir" -o "$mixed_header"

PYTHONPATH="$repository_root/src${PYTHONPATH:+:$PYTHONPATH}" \
python3 "$repository_root/tools/assemble_portable_systemc_handoff.py" \
  --repo-root "$repository_root" \
  --prepared-ir "$prepared_ir" \
  --mixed-header "$mixed_header" \
  --frontend-record "$stage_dir/02_frontend_reachable_design.json" \
  --container "$top_module" \
  --modules "$module_csv" \
  --circt-opt "$circt_build/bin/circt-opt" \
  --output "$work_root/project"

bash "$repository_root/scripts/run_portable_handoff_verification.sh" \
  "$work_root/project" \
  "$work_root/build" \
  "$systemc_cmake_root"

echo "PORTABLE_DSC_MIXED_PROJECT=PASS"
echo "PROJECT_DIR=$work_root/project"
