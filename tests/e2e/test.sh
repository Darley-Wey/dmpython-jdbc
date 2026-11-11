#!/usr/bin/env bash
# Build/install the working tree, then test the installed package from macOS.
set -euo pipefail
root=$(cd "$(dirname "$0")/../.." && pwd)
cd "$root"
python="$root/.venv-e2e/bin/python"
if [[ ! -x "$python" ]]; then
    uv venv --python 3.13 "$root/.venv-e2e"
fi
uv pip install --python "$python" --reinstall-package dmpython-jdbc \
    "$root" 'async-timeout>=4,<6' 'python-dotenv>=1.2,<2'
uv pip install --python "$python" --no-deps 'dmAsync==1.0.0'

# Keep unit-test sys.modules patches out of the live-test process.
"$python" -I -m unittest discover -s tests -p 'test_dmasync.py' -v
exec "$python" -I tests/e2e/run.py "$@"
