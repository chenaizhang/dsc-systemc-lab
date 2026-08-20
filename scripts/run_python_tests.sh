#!/usr/bin/env bash
set -euo pipefail

script_dir=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
repository_root=$(cd "$script_dir/.." && pwd)
venv_dir=$repository_root/.work/venv
python_bin=$venv_dir/bin/python

bootstrap_python="${DSCFLOW_PYTHON:-}"
if [[ -z "$bootstrap_python" ]]; then
    for candidate in "$repository_root/.venv/bin/python" python3.13 python3.12 python3.11 python3.10 python3; do
        if command -v "$candidate" >/dev/null 2>&1 && "$candidate" -c \
            'import sys; raise SystemExit(sys.version_info < (3, 10))' 2>/dev/null; then
            bootstrap_python=$(command -v "$candidate")
            break
        fi
    done
fi
if [[ -z "$bootstrap_python" ]]; then
    echo "error: Python 3.10 or newer is required" >&2
    exit 2
fi
if [[ ! -x "$python_bin" ]] || ! "$python_bin" -c \
    'import sys; raise SystemExit(sys.version_info < (3, 10))' 2>/dev/null; then
    "$bootstrap_python" -m venv --clear "$venv_dir"
fi
"$python_bin" -m pip install -q -e "$repository_root[dev]"
exec "$python_bin" -m pytest -q
