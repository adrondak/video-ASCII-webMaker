#!/usr/bin/env bash
# Zip a publish directory for upload (e.g. SiteGround File Manager → Extract).
#   scripts/package-zip.sh [dir] [output.zip]
# The archive contains the folder's *contents* (including the hidden .htaccess)
# so extracting it inside public_html/ or a subfolder gives a working site.
set -euo pipefail
dir="${1:-www}"
out="${2:-dist/$(basename "$dir")-site.zip}"
[ -f "$dir/index.html" ] && { [ -f "$dir/manifest.json" ] || [ -f "$dir/live.json" ]; } || { echo "$dir is not a publish directory" >&2; exit 1; }
mkdir -p "$(dirname "$out")"
out_abs="$(cd "$(dirname "$out")" && pwd)/$(basename "$out")"
rm -f "$out_abs"
(cd "$dir" && zip -q -X -r "$out_abs" . -x ".DS_Store" -x "*/.DS_Store")
echo "wrote $out ($(du -h "$out_abs" | cut -f1))"
unzip -l "$out_abs" | tail -n +4 | sed '$d' | sed '$d' | awk '{print "  " $4}'
