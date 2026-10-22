#!/usr/bin/env bash
# Serve a publish directory locally (with HTTP Range support):  scripts/serve.sh [dir] [port]
set -euo pipefail
dir="${1:-www}"
port="${2:-8000}"
exec python3 "$(dirname "$0")/serve.py" "$dir" "$port"
