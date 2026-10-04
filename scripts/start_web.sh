#!/usr/bin/env sh
# Use a hosting provider's PORT while preserving WebSocket and XSRF support.
set -eu
cd "$(dirname "$0")/.."
exec python -m streamlit run web_app.py --server.address=0.0.0.0 --server.port="${PORT:-8501}"
