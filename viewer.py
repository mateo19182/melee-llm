"""Serve Slippi Lab and the replays/ folder on the Tailscale IP (never 0.0.0.0)."""
import html
import http.server
import os
from functools import partial
from pathlib import Path

ROOT = Path(__file__).parent
DIST = ROOT / "vendor/slippilab/dist"
REPLAYS = ROOT / "replays"
HOST, PORT = os.environ.get("BIND", "100.83.166.6"), int(os.environ.get("PORT", "8767"))


class Handler(http.server.SimpleHTTPRequestHandler):
    def translate_path(self, path):
        if path.startswith("/replays/"):
            return str(REPLAYS / Path(path.split("?")[0]).name)
        return super().translate_path(path)

    def do_GET(self):
        if self.path in ("/list", "/list/"):
            files = sorted(REPLAYS.glob("**/*.slp"), key=lambda f: f.stat().st_mtime, reverse=True)
            rows = "".join(
                f'<li><a href="/?replayUrl=/replays/{html.escape(f.name)}">{html.escape(f.name)}</a></li>'
                for f in files)
            body = f"<h1>Replays</h1><ul>{rows or '<li>none yet</li>'}</ul>".encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.end_headers()
            self.wfile.write(body)
            return
        super().do_GET()


if __name__ == "__main__":
    REPLAYS.mkdir(exist_ok=True)
    print(f"http://m19182:{PORT}/list")
    http.server.ThreadingHTTPServer((HOST, PORT), partial(Handler, directory=str(DIST))).serve_forever()
