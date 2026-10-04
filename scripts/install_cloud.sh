#!/usr/bin/env bash
# Refresh the current isolated cloud checkout without modifying sources or locks.
set -euo pipefail
cd /workspace/btc-trading-analyzer
python3 -c 'import sys; assert sys.version_info >= (3, 11), "Python 3.11+ required"'
if [ ! -x .venv/bin/python ]; then
  python3 -m venv .venv
fi
if command -v uv >/dev/null 2>&1; then
  uv --cache-dir /workspace/.uv-cache pip sync requirements.lock --python .venv/bin/python
else
  PIP_CACHE_DIR=/workspace/.pip-cache .venv/bin/python -m pip install -r requirements.lock
fi
.venv/bin/python scripts/smoke.py
