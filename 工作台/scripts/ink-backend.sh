#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/../backend"
# Separate from other local apps using 8000. Only the /api/ink proxy uses this port.
exec uv run uvicorn api.app:app --host 127.0.0.1 --port "${INK_BACKEND_PORT:-8011}"
