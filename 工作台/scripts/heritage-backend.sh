#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/../backend"
export SFA_CORS_ORIGINS="http://127.0.0.1:3001,http://localhost:3001"
exec .venv/bin/python -m uvicorn api.app:app --host 127.0.0.1 --port "${HERITAGE_BACKEND_PORT:-8012}"
