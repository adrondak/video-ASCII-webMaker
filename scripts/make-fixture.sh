#!/usr/bin/env bash
# Generate synthetic test videos with FFmpeg (no external media needed).
#
#   scripts/make-fixture.sh [output-dir]      (default: tests/fixtures)
#
# landscape.mp4  5 s, 640x360 @ 30 fps: moving gradient, hard cut at 2.5 s to a
#                test pattern, a white "clock" box in the top-left for the first
#                0.1 s of every second, and a 1 kHz click on every whole second.
# silent.mp4     3 s, 320x180, no audio stream.
# portrait.mp4   2 s, 360x640 with a 440 Hz tone.
# rotated.mp4    landscape.mp4 with 90° display-rotation metadata (plays portrait).
set -euo pipefail
out="${1:-tests/fixtures}"
mkdir -p "$out"

if ffmpeg -hide_banner -encoders 2>/dev/null | grep -q libx264; then
  vcodec=(-c:v libx264 -pix_fmt yuv420p -preset veryfast -crf 18)
else
  vcodec=(-c:v mpeg4 -q:v 3 -pix_fmt yuv420p)
fi
common=(-hide_banner -loglevel error -y)
clock="drawbox=enable='lt(mod(t,1),0.1)':x=0:y=0:w=iw/8:h=ih/8:color=white:t=fill"
click="aevalsrc='if(lt(mod(t,1),0.03),0.8*sin(2*PI*1000*t),0)':s=48000:d=5"

ffmpeg "${common[@]}" \
  -f lavfi -i "nullsrc=s=640x360:r=30:d=2.5,geq=lum='mod(X+T*256,W)*255/W':cb=128:cr=128" \
  -f lavfi -i "testsrc2=s=640x360:r=30:d=2.5" \
  -f lavfi -i "$click" \
  -filter_complex "[0:v]format=yuv420p[a];[1:v]format=yuv420p[b];[a][b]concat=n=2:v=1:a=0,${clock}[v]" \
  -map "[v]" -map 2:a "${vcodec[@]}" -c:a aac -b:a 128k -shortest "$out/landscape.mp4"

ffmpeg "${common[@]}" -f lavfi -i "testsrc2=s=320x180:r=24:d=3" \
  -vf "$clock" "${vcodec[@]}" -an "$out/silent.mp4"

ffmpeg "${common[@]}" -f lavfi -i "testsrc2=s=360x640:r=25:d=2" \
  -f lavfi -i "sine=f=440:d=2:sample_rate=48000" \
  -vf "$clock" "${vcodec[@]}" -c:a aac -b:a 96k -shortest "$out/portrait.mp4"

ffmpeg "${common[@]}" -display_rotation:v:0 90 -i "$out/landscape.mp4" -c copy "$out/rotated.mp4"

echo "fixtures written to $out:"
ls -l "$out"/*.mp4
