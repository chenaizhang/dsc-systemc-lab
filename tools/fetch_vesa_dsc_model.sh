#!/usr/bin/env bash
set -euo pipefail

destination=${1:-third_party/vesa-dsc-model-20211213}
archive="$destination/DSC_model_20211213.zip"
model_root="$destination/DSC_model_20211213"
expected_sha256=f2339edb1d5603d2f3ca5fbb6ca089b18ff73c43088352fa7c3b59df03e3ee2c
download_url='https://app.box.com/index.php?rm=box_download_shared_file&shared_name=vcocw3z73ta09txiskj7cnk6289j356b&file_id=f_996525137424'

if [[ -f "$model_root/source/dsc_codec.c" ]]; then
    printf '%s\n' "$model_root"
    exit 0
fi

mkdir -p "$destination"
curl -L --fail --silent --show-error "$download_url" -o "$archive"
if command -v sha256sum >/dev/null 2>&1; then
    actual_sha256=$(sha256sum "$archive" | awk '{print $1}')
else
    actual_sha256=$(shasum -a 256 "$archive" | awk '{print $1}')
fi
if [[ "$actual_sha256" != "$expected_sha256" ]]; then
    printf 'VESA DSC model checksum mismatch: expected %s, got %s\n' \
        "$expected_sha256" "$actual_sha256" >&2
    exit 1
fi
unzip -q "$archive" -d "$destination"
printf '%s\n' "$model_root"
