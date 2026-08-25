#!/usr/bin/env bash
set -euo pipefail

if [[ $# -lt 4 || $# -gt 5 ]]; then
  echo "用法: $0 <config.json> <RTL输入目录> <输出目录> <CIRCT构建目录> [CIRCT运行库目录]" >&2
  exit 2
fi

pipeline_config=$1
rtl_input_root=$2
pipeline_output_root=$3
circt_build_root=$4
circt_runtime_library=${5:-"$circt_build_root/lib"}
project_root=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)

case "$(uname -m)" in
  x86_64|amd64) ;;
  *)
    echo "该脚本只用于正式的 x86_64 EDA 验证环境。" >&2
    exit 2
    ;;
esac

for required_path in \
  "$pipeline_config" \
  "$rtl_input_root" \
  "$circt_build_root/bin/circt-opt" \
  "$circt_build_root/bin/circt-verilog" \
  "$circt_build_root/bin/circt-translate"; do
  if [[ ! -e "$required_path" ]]; then
    echo "缺少输入或工具: $required_path" >&2
    exit 2
  fi
done

cd "$project_root"
if ! PYTHONPATH="$project_root/src${PYTHONPATH:+:$PYTHONPATH}" \
  python3 -m dscflow skills; then
  echo "首次使用缺少项目 Skill，请先运行：python3 -m dscflow skills --install" >&2
  exit 2
fi

PYTHONPATH="$project_root/src${PYTHONPATH:+:$PYTHONPATH}" \
python3 -m dscflow circt run \
  --config "$pipeline_config" \
  --input-root "$rtl_input_root" \
  --output-root "$pipeline_output_root" \
  --circt-root "$circt_build_root" \
  --circt-library-path "$circt_runtime_library"
