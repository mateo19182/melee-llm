"""Loopback HTTP proxy that adds the CLIProxy key, so a coding agent can use CLIProxy without holding the key.

The agent gets ANTHROPIC_BASE_URL=http://127.0.0.1:<port> and a dummy token; this forwards each request
to the upstream with the real Authorization header and streams the answer back.
"""
from __future__ import annotations

import http.client
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit

HOP = {"connection", "keep-alive", "transfer-encoding", "content-length", "host", "authorization", "x-api-key"}


def start(upstream: str, key: str) -> tuple[ThreadingHTTPServer, str]:
    """Serve on a free loopback port in a daemon thread. Returns (server, base_url)."""
    up = urlsplit(upstream)

    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.0"  # one request per connection: the reply ends when we close

        def _forward(self) -> None:
            body = self.rfile.read(int(self.headers.get("Content-Length") or 0))
            headers = {k: v for k, v in self.headers.items() if k.lower() not in HOP}
            headers["Authorization"] = f"Bearer {key}"
            conn = http.client.HTTPConnection(up.hostname, up.port, timeout=900)
            try:
                conn.request(self.command, self.path, body or None, headers)
                resp = conn.getresponse()
                self.send_response(resp.status)
                for k, v in resp.getheaders():
                    if k.lower() not in HOP:
                        self.send_header(k, v)
                self.end_headers()
                while chunk := resp.read1(65536):
                    self.wfile.write(chunk)
                    self.wfile.flush()
            except OSError:
                pass
            finally:
                conn.close()

        do_GET = do_POST = _forward

        def log_message(self, *a) -> None:
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    server.daemon_threads = True
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, f"http://127.0.0.1:{server.server_address[1]}"
