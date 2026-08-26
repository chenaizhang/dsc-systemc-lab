#!/usr/bin/env bash
set -euo pipefail

if [[ $# -lt 2 || $# -gt 3 ]]; then
  echo "用法: $0 <交接工程目录> <构建目录> [SystemC CMake目录]" >&2
  exit 2
fi

handoff_source=$1
handoff_build=$2
systemc_cmake_root=${3:-}

if [[ "$(uname -m)" != "x86_64" ]]; then
  echo "正式交接验证只能在 x86_64 Linux 执行。" >&2
  exit 2
fi

for required_tool in cmake ctest verilator c++; do
  command -v "$required_tool" >/dev/null 2>&1 || {
    echo "缺少构建工具: $required_tool" >&2
    exit 2
  }
done

verification_dir=$handoff_source/verification
mkdir -p "$verification_dir"
{
  printf 'architecture=%s\n' "$(uname -m)"
  printf 'kernel=%s\n' "$(uname -sr)"
  cmake --version | head -n 1
  c++ --version | head -n 1
  verilator --version
} > "$verification_dir/tool_versions.txt"

cmake_args=(
  -S "$handoff_source"
  -B "$handoff_build"
  -DCMAKE_BUILD_TYPE=Release
)
if command -v ninja >/dev/null 2>&1; then
  cmake_args+=(-G Ninja)
fi
if [[ -n "$systemc_cmake_root" ]]; then
  cmake_args+=("-DCMAKE_PREFIX_PATH=$systemc_cmake_root")
fi

cmake "${cmake_args[@]}" 2>&1 | tee "$verification_dir/cmake_configure.log"
cmake --build "$handoff_build" --parallel 2 2>&1 \
  | tee "$verification_dir/cmake_build.log"
ctest --test-dir "$handoff_build" --output-on-failure 2>&1 \
  | tee "$verification_dir/ctest.log"
printf 'PORTABLE_SYSTEMC_HANDOFF=PASS\n' > "$verification_dir/status.txt"
