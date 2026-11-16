#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/../frontend"
export BACKEND_API_URL="http://127.0.0.1:${HERITAGE_BACKEND_PORT:-8012}"
export INK_BACKEND_API_URL="http://127.0.0.1:${HERITAGE_BACKEND_PORT:-8012}"
exec npm run dev -- --hostname 127.0.0.1 --port "${HERITAGE_FRONTEND_PORT:-3001}"
