"""Serve Slippi Lab, the replays/ folder and a live MJPEG stream of display :99.

Bound to the Tailscale IP only (never 0.0.0.0). Pages: /list (replays), /watch (live game).
"""
import html
import http.server
import json
import os
import re
import subprocess
import threading
from functools import partial
from pathlib import Path

ROOT = Path(__file__).parent
DIST = ROOT / "vendor/slippilab/dist"
REPLAYS = ROOT / "replays"
HOST, PORT = os.environ.get("BIND", "100.83.166.6"), int(os.environ.get("PORT", "8767"))
DISPLAY, SCREEN, OUT = os.environ.get("LIVE_DISPLAY", ":99"), "1280x960", "960:720"

WATCH_HTML = b"""<!doctype html><title>melee live</title>
<style>html,body{margin:0;height:100%;background:#000}img{width:100%;height:100%;object-fit:contain}</style>
<img src="/live">"""


class LiveStream:
    """One ffmpeg x11grab → JPEG frames, fanned out to every viewer; runs only while someone watches."""

    def __init__(self):
        self.cond, self.frame, self.seq, self.viewers, self.proc = threading.Condition(), b"", 0, 0, None

    @staticmethod
    def _game_window() -> tuple[str, str]:
        """(size, display+offset) of Dolphin's game window, or the whole screen if it isn't open."""
        tree = subprocess.run(["xwininfo", "-root", "-tree"], env={**os.environ, "DISPLAY": DISPLAY},
                              capture_output=True, text=True).stdout
        for line in tree.splitlines():
            if "GALE01" in line and (m := re.search(r"(\d+)x(\d+)\+(\d+)\+(\d+)\s+\+(\d+)\+(\d+)", line)):
                w, h, *_, x, y = m.groups()
                return f"{w}x{h}", f"{DISPLAY}+{x},{y}"
        return SCREEN, DISPLAY

    def _capture(self):
        size, source = self._game_window()
        self.proc = subprocess.Popen(
            ["ffmpeg", "-loglevel", "error", "-f", "x11grab", "-draw_mouse", "0", "-framerate", "60",
             "-video_size", size, "-i", source, "-vf", f"scale={OUT}:flags=lanczos", "-c:v", "mjpeg", "-q:v", "5",
             "-f", "image2pipe", "-"], stdout=subprocess.PIPE)
        buf = b""
        while chunk := self.proc.stdout.read1(1 << 16):
            buf += chunk
            # In baseline JPEG, FF D9 only occurs as the end-of-image marker (data bytes FF are stuffed).
            while (end := buf.find(b"\xff\xd9")) != -1:
                with self.cond:
                    self.frame, self.seq = buf[:end + 2], self.seq + 1
                    self.cond.notify_all()
                buf = buf[end + 2:]
        with self.cond:
            self.proc = None
            self.cond.notify_all()

    def join(self):
        with self.cond:
            self.viewers += 1
            if self.proc is None:
                threading.Thread(target=self._capture, daemon=True).start()

    def leave(self):
        with self.cond:
            self.viewers -= 1
            if self.viewers == 0 and self.proc is not None:
                self.proc.terminate()

    def frames(self):
        seq = -1
        while True:
            with self.cond:
                if not self.cond.wait_for(lambda: self.seq != seq, timeout=5):
                    return
                seq, frame = self.seq, self.frame
            yield frame


LIVE = LiveStream()


def find_replay(name: str) -> Path | None:
    return next(REPLAYS.rglob(Path(name).name), None)


class Handler(http.server.SimpleHTTPRequestHandler):
    def translate_path(self, path):
        if path.startswith("/replays/"):
            found = find_replay(path.split("?")[0])
            return str(found) if found else str(REPLAYS / "missing")
        return super().translate_path(path)

    def _send(self, body: bytes, ctype="text/html"):
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path in ("/list", "/list/"):
            files = sorted(REPLAYS.rglob("*.slp"), key=lambda f: f.stat().st_mtime, reverse=True)
            rows = "".join(
                f'<li><a href="/?replayUrl=/replays/{html.escape(f.name)}">{html.escape(f.name)}</a></li>'
                for f in files)
            return self._send(f'<p><a href="/arena">arena standings</a> · live: <a href="http://m19182:8889/live/">WebRTC (H.264, smooth)</a> · <a href="/watch">MJPEG fallback</a></p><h1>Replays</h1><ul>{rows or "<li>none yet</li>"}</ul>'.encode())
        if self.path == "/arena":
            path = ROOT / "arena/standings.json"
            data = json.loads(path.read_text()) if path.exists() else {"table": [], "games": 0, "updated": "never"}
            rows = "".join(f"<tr><td>{html.escape(r['entrant'])}</td><td>{r['elo']}</td><td>{r['wins']}-{r['losses']}"
                           f"{'-' + str(r['draws']) if r['draws'] else ''}</td></tr>" for r in data["table"])
            recent = (ROOT / "arena/results.jsonl").read_text().splitlines()[-15:] if (ROOT / "arena/results.jsonl").exists() else []
            games = "".join(
                f"<li>{html.escape(g['p1'])} ({g['char1'].title()}) vs {html.escape(g['p2'])} ({g['char2'].title()}), "
                f"{g['stage'].replace('_', ' ').title()}: winner P{g['winner']} {g['stocks']}"
                + (f' <a href="/?replayUrl=/replays/{html.escape(Path(g["replay"]).name)}">replay</a>' if g.get("replay") else "")
                + "</li>" for g in map(json.loads, reversed(recent)))
            return self._send(f"""<meta http-equiv="refresh" content="30"><style>body{{font-family:sans-serif;margin:2em}}
td,th{{padding:4px 12px;text-align:left}}</style><p><a href="http://m19182:8889/live/">watch live</a></p>
<h1>Arena</h1><p>{data['games']} games, updated {data['updated']}</p>
<table><tr><th>Bot</th><th>Elo</th><th>W-L</th></tr>{rows}</table><h2>Recent</h2><ul>{games}</ul>""".encode())
        if self.path == "/watch":
            return self._send(WATCH_HTML)
        if self.path == "/live":
            self.send_response(200)
            self.send_header("Content-Type", "multipart/x-mixed-replace; boundary=frame")
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            LIVE.join()
            try:
                for frame in LIVE.frames():
                    self.wfile.write(b"--frame\r\nContent-Type: image/jpeg\r\nContent-Length: %d\r\n\r\n" % len(frame))
                    self.wfile.write(frame + b"\r\n")
            except (BrokenPipeError, ConnectionResetError):
                pass
            finally:
                LIVE.leave()
            return
        super().do_GET()


if __name__ == "__main__":
    REPLAYS.mkdir(exist_ok=True)
    print(f"http://m19182:{PORT}/list  ·  http://m19182:{PORT}/watch")
    http.server.ThreadingHTTPServer((HOST, PORT), partial(Handler, directory=str(DIST))).serve_forever()
