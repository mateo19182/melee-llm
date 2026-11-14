#!/usr/bin/env bash
# Publish Dolphin's game window on display :99 as low-latency H.264 (NVENC) to mediamtx, at native size.
# mediamtx starts this on demand when a viewer connects (scripts/mediamtx.yml).
# runner.Console keeps the live game window at (0, 0) and runner.LIVE_WINDOW in size, so the capture area is fixed:
# no waiting for the window, and a stream that outlives a Dolphin restart stays aligned.
DISPLAY_NAME=${LIVE_DISPLAY:-:99}
exec ffmpeg -loglevel error -f x11grab -draw_mouse 0 -framerate 60 -video_size 1168x960 -i "$DISPLAY_NAME+0,0" -vf format=yuv420p \
  -c:v h264_nvenc -preset p1 -tune ull -zerolatency 1 -profile:v baseline -rc cbr -b:v 6M -maxrate 6M -bufsize 1.5M -g 60 -bf 0 \
  -f rtsp -rtsp_transport tcp "rtsp://127.0.0.1:8554/$MTX_PATH"
