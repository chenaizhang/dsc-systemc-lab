#!/usr/bin/env bash
set -euo pipefail

if [[ $# -ne 1 ]]; then
    printf 'Usage: %s BUILD_DIR\n' "$0" >&2
    exit 2
fi
if [[ $(uname -m) != x86_64 ]]; then
    printf 'Verification is supported on Linux x86_64 only.\n' >&2
    exit 2
fi

root=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
build_dir=$1
executable=$build_dir/native_image_differential
test -x "$executable" || {
    printf 'Build the handoff first; executable is missing: %s\n' "$executable" >&2
    exit 2
}

set +e
DSCFLOW_NATIVE_IDLE_LIMIT=1 timeout 300s "$executable" \
    "$root/tests/data/deterministic_rgb.ppm" \
    "$root/tests/data/deterministic_rgb.dsc" \
    "$build_dir/native_payload.bin" \
    >"$build_dir/known-status.log" 2>&1
result=$?
set -e
tail -n 20 "$build_dir/known-status.log"

if [[ $result -ne 3 ]]; then
    printf 'Unexpected differential exit code: %s (expected known mismatch code 3).\n' "$result" >&2
    exit 1
fi
if ! grep -q 'pixels_accepted=1536' "$build_dir/known-status.log" \
    || ! grep -q 'output_bytes=0' "$build_dir/known-status.log" \
    || ! grep -q 'golden_bytes=1536' "$build_dir/known-status.log"; then
    printf 'The observed behavior differs from the recorded handoff status.\n' >&2
    exit 1
fi
printf 'KNOWN_FUNCTIONAL_FAILURE_REPRODUCED=PASS\n'
