#!/usr/bin/env bash
# Publish display :99 (cropped to Dolphin's game window) as low-latency H.264 (NVENC) to mediamtx.
# mediamtx starts this on demand when a viewer connects (scripts/mediamtx.yml).
DISPLAY_NAME=${LIVE_DISPLAY:-:99}
geom=$(DISPLAY=$DISPLAY_NAME xwininfo -root -tree 2>/dev/null | grep GALE01 | grep -oE '[0-9]+x[0-9]+\+[0-9]+\+[0-9]+ +\+[0-9]+\+[0-9]+' | head -1)
if [ -n "$geom" ]; then
  size=${geom%%+*}; pos=$(echo "$geom" | awk '{print $2}'); x=$(echo "$pos" | cut -d+ -f2); y=$(echo "$pos" | cut -d+ -f3)
  src="$DISPLAY_NAME+$x,$y"
else
  size=1280x960; src=$DISPLAY_NAME
fi
exec ffmpeg -loglevel error -f x11grab -draw_mouse 0 -framerate 60 -video_size "$size" -i "$src" \
  -vf "scale=960:720:flags=lanczos,format=yuv420p" \
  -c:v h264_nvenc -preset p1 -tune ull -zerolatency 1 -profile:v baseline -rc cbr -b:v 4M -maxrate 4M -bufsize 1M -g 60 -bf 0 \
  -f rtsp -rtsp_transport tcp "rtsp://127.0.0.1:8554/$MTX_PATH"
