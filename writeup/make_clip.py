"""Cut a commentated clip from a screen recording of the live slot (:99) and the game's commentary log.

    python3 writeup/make_clip.py REC.mp4 START_TS GAME.p0.commentary.jsonl OUT.mp4 [--from S] [--len S] [--title TEXT]

REC.mp4 is an x11grab of :99 started at wall time START_TS (seconds since the epoch). Each caster line's MP3 is
placed at the moment it describes (its `ts`), never over the previous clip, and the line is burned in as a subtitle.
--from/--len pick the window in seconds after the first commentary event. Needs ffmpeg with libass.
"""
from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path


def stamp(t: float) -> str:
    h, rem = divmod(max(t, 0), 3600)
    m, s = divmod(rem, 60)
    return f"{int(h)}:{int(m):02d}:{s:05.2f}"


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("rec"), ap.add_argument("start_ts", type=float), ap.add_argument("log"), ap.add_argument("out")
    ap.add_argument("--from", dest="t0", type=float, default=-3.0)
    ap.add_argument("--len", dest="length", type=float, default=110.0)
    ap.add_argument("--title", default="")
    ap.add_argument("--crop", default="1168:960:0:0", help="ffmpeg crop w:h:x:y of the Dolphin window on :99")
    a = ap.parse_args()

    recs = [json.loads(x) for x in open(a.log)]
    first = min(r["ts"] for r in recs)
    win0 = first - a.start_ts + a.t0  # window start, seconds into the recording
    win1 = win0 + a.length
    clips, subs, end = [], [], 0.0
    for r in recs:
        if r.get("type") != "line" or not r.get("audio"):
            continue
        mp3 = Path(r["audio"])
        if not mp3.is_absolute():
            mp3 = Path(a.log).parent / mp3
        t = max(r["ts"] - a.start_ts - win0, end + 0.2)
        dur = float(r.get("audio_s") or 2.5)
        if t < 0 or t + dur > a.length:
            continue
        clips.append((t, mp3))
        subs.append((t, t + dur, r["speaker"], r["text"]))
        end = t + dur

    ass = Path(a.out).with_suffix(".ass")
    head = ("[Script Info]\nScriptType: v4.00+\nPlayResX: 1168\nPlayResY: 960\n\n[V4+ Styles]\n"
            "Format: Name, Fontname, Fontsize, PrimaryColour, OutlineColour, BackColour, Bold, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV\n"
            "Style: Charlie,DejaVu Sans,34,&H00FFFFFF,&H00000000,&H90000000,1,3,2,0,2,60,60,250\n"
            "Style: Laura,DejaVu Sans,34,&H00A0F0FF,&H00000000,&H90000000,1,3,2,0,2,60,60,250\n"
            "Style: Title,DejaVu Sans,24,&H00FFFFFF,&H00000000,&HA0000000,1,3,2,0,8,40,40,30\n\n"
            "[Events]\nFormat: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n")
    lines = [f"Dialogue: 0,{stamp(s)},{stamp(e)},{who},,0,0,0,,{who.upper()}: {txt}" for s, e, who, txt in subs]
    if a.title:
        lines.insert(0, f"Dialogue: 0,{stamp(0)},{stamp(a.length)},Title,,0,0,0,,{a.title}")
    ass.write_text(head + "\n".join(lines) + "\n")

    cmd = ["ffmpeg", "-loglevel", "error", "-y", "-ss", f"{win0:.2f}", "-t", f"{a.length:.2f}", "-i", a.rec]
    for _, mp3 in clips:
        cmd += ["-i", str(mp3)]
    delays = "".join(f"[{i + 1}:a]adelay={int(t * 1000)}:all=1[a{i}];" for i, (t, _) in enumerate(clips))
    mix = "".join(f"[a{i}]" for i in range(len(clips)))
    graph = (f"[0:v]crop={a.crop},subtitles={ass}[v];{delays}{mix}amix=inputs={len(clips)}:normalize=0:dropout_transition=0,"
             f"apad,atrim=0:{a.length:.2f}[a]")
    cmd += ["-filter_complex", graph, "-map", "[v]", "-map", "[a]", "-c:v", "libx264", "-preset", "medium",
            "-crf", "23", "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "128k", "-movflags", "+faststart", a.out]
    subprocess.run(cmd, check=True)
    print(f"{a.out}: {len(clips)} lines over {a.length:.0f} s from {win0:.1f} s into the recording")


if __name__ == "__main__":
    main()
