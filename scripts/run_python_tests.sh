#!/usr/bin/env bash
set -euo pipefail

script_dir=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
repository_root=$(cd "$script_dir/.." && pwd)
venv_dir=$repository_root/.work/venv
python_bin=$venv_dir/bin/python

if [[ ! -x "$python_bin" ]]; then
    python3 -m venv "$venv_dir"
fi
if ! "$python_bin" -c 'import pytest' >/dev/null 2>&1; then
    "$python_bin" -m pip install -e "$repository_root[dev]"
fi
exec "$python_bin" -m pytest -q

