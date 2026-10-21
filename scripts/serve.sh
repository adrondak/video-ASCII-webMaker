#!/usr/bin/env bash
# Serve a publish directory locally:  scripts/serve.sh [dir] [port]
set -euo pipefail
dir="${1:-www}"
port="${2:-8000}"
echo "Serving $dir at http://localhost:$port/  (Ctrl+C to stop)"
exec python3 -m http.server "$port" --bind 127.0.0.1 --directory "$dir"
