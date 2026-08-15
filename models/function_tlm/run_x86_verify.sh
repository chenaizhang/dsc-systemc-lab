#!/usr/bin/env bash
set -euo pipefail

script_dir=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
repository_root=$(cd "$script_dir/../.." && pwd)
toolchain_dir=${DSCFLOW_VESA_ROOT:-$repository_root/third_party/vesa-dsc-model-20211213}
build_dir=${DSCFLOW_BUILD_DIR:-$repository_root/.work/build/function-tlm}
run_dir=${DSCFLOW_RUN_DIR:-$repository_root/.work/runs/vesa-differential}

for command in curl unzip gcc g++ cmake make python3; do
    if ! command -v "$command" >/dev/null 2>&1; then
        printf '缺少依赖：%s\n' "$command" >&2
        exit 2
    fi
done

if [[ "$(uname -m)" != "x86_64" ]]; then
    printf '正式验证要求 x86_64，当前架构为 %s\n' "$(uname -m)" >&2
    exit 2
fi

model_root=$(
    "$repository_root/tools/fetch_vesa_dsc_model.sh" "$toolchain_dir"
)
make -C "$model_root/source" all

cmake -S "$script_dir" -B "$build_dir" \
    -DDSCFLOW_ENABLE_VESA_CODEC=ON \
    -DVESA_DSC_MODEL_ROOT="$model_root"
cmake --build "$build_dir" --parallel
ctest --test-dir "$build_dir" --output-on-failure

python3 "$repository_root/tools/run_dsc_reference_differential.py" \
    --model-root "$model_root" \
    --adapter-test "$build_dir/vesa_reference_codec_contract" \
    --work-dir "$run_dir" \
    --report "$run_dir/report.json"

printf '\n验证完成，报告：%s\n' "$run_dir/report.json"
