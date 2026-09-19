#!/usr/bin/env bash
set -euo pipefail

if [[ $# -ne 5 ]]; then
    printf 'Usage: %s SYSTEMC_HEADER HW_IR INPUT_PPM REFERENCE_DSC OUTPUT_TAR_GZ\n' "$0" >&2
    exit 2
fi
if [[ $(uname -m) != x86_64 ]]; then
    printf 'The distributable handoff must be packaged on Linux x86_64.\n' >&2
    exit 2
fi

systemc_header=$1
hw_ir=$2
input_ppm=$3
reference_dsc=$4
output_archive=$5
script_dir=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
repository_root=$(cd "$script_dir/.." && pwd)

for required in "$systemc_header" "$hw_ir" "$input_ppm" "$reference_dsc"; do
    test -f "$required" || { printf 'Missing input: %s\n' "$required" >&2; exit 2; }
done
for command in tar sha256sum mktemp; do
    command -v "$command" >/dev/null 2>&1 || { printf 'Missing tool: %s\n' "$command" >&2; exit 2; }
done

temporary_root=$(mktemp -d)
trap 'rm -rf "$temporary_root"' EXIT
package_name=dsc-systemc-current-handoff-20260919-linux-x86_64
package_root=$temporary_root/$package_name
mkdir -p "$package_root"/{generated,ir,tests/data,scripts,evidence,reports}

install -m 0644 "$systemc_header" "$package_root/generated/depth_6.systemc.hpp"
install -m 0644 "$hw_ir" "$package_root/ir/dsc_encoder.hw.mlir"
install -m 0644 "$input_ppm" "$package_root/tests/data/deterministic_rgb.ppm"
install -m 0644 "$reference_dsc" "$package_root/tests/data/deterministic_rgb.dsc"
install -m 0644 "$repository_root/models/cycle_systemc/tests/native_image_differential.cpp" \
    "$package_root/tests/native_image_differential.cpp"
install -m 0644 "$repository_root/packaging/current_systemc/CMakeLists.txt" \
    "$package_root/CMakeLists.txt"
install -m 0755 "$repository_root/packaging/current_systemc/verify_known_status.sh" \
    "$package_root/scripts/verify_known_status.sh"
install -m 0644 "$repository_root/docs/handoffs/current_systemc_delivery_zh.md" \
    "$package_root/README_ZH.md"
install -m 0644 "$repository_root/docs/reports/circt_native_image_differential_x86_zh.md" \
    "$package_root/reports/circt_native_image_differential_x86_zh.md"
install -m 0644 "$repository_root/evidence/results/circt_native_image_x86/validation.json" \
    "$package_root/evidence/validation.json"

(
    cd "$package_root"
    find . -type f ! -name SHA256SUMS -print0 | sort -z | xargs -0 sha256sum >SHA256SUMS
)
mkdir -p "$(dirname "$output_archive")"
tar -C "$temporary_root" -czf "$output_archive" "$package_name"
sha256sum "$output_archive" >"$output_archive.sha256"
printf 'HANDOFF_ARCHIVE=%s\n' "$output_archive"
printf 'HANDOFF_SHA256=%s\n' "$(cut -d' ' -f1 "$output_archive.sha256")"
