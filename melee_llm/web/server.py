"""Web UI server (Starlette). Bind 127.0.0.1 only: Cloudflare Tunnel puts it at https://melee.m19182.dev.

Anyone can browse and queue limited matches; settings, cancelling and the paid voice need the operator (web/auth.py).

    BIND=127.0.0.1 PORT=8770 python -m melee_llm.web.server
"""
from __future__ import annotations

import asyncio
import json
import os
import re
import time
from pathlib import Path

import httpx
import uvicorn
from starlette.applications import Starlette
from starlette.background import BackgroundTask
from starlette.requests import Request
from starlette.responses import FileResponse, HTMLResponse, JSONResponse, PlainTextResponse, RedirectResponse, Response, StreamingResponse
from starlette.routing import Mount, Route
from starlette.staticfiles import StaticFiles

from melee_llm.paths import DATA, REPLAYS, ROOT, VOICE_HEARTBEAT
from melee_llm.web import auth, docs, games, jobs, logs, registry, specs, training

STATIC = Path(__file__).parent / "static"
SLIPPILAB = ROOT / "vendor/slippilab/dist"
SITE = "https://melee.m19182.dev"
# Routes that show the same page as another: "/" is the live view, and /docs opens the research doc.
ALIASES = {"/live": "/", "/docs": "/docs/research"}
HLS_UPSTREAM = os.environ.get("MELEE_HLS", "http://127.0.0.1:8888/live/")
_hls = httpx.AsyncClient(timeout=httpx.Timeout(30.0, connect=5.0))


def ok(data, status: int = 200) -> JSONResponse:
    return JSONResponse(data, status_code=status)


def blocking(fn, *a, **kw):
    return asyncio.to_thread(fn, *a, **kw)


def admin(request: Request):
    return blocking(auth.is_admin, request)


def operator_only(handler):
    async def guarded(request: Request) -> Response:
        if request.method != "GET" and not await admin(request):
            return ok({"error": "only the operator can do that"}, 403)
        return await handler(request)
    return guarded


# --------------------------------------------------------------------------- pages and assets

class CachedStatic(StaticFiles):
    """Static files with an explicit Cache-Control. Without one, Cloudflare's edge and browsers cache JS/CSS
    heuristically and keep serving copies from earlier deploys."""

    def __init__(self, *a, cache: str, **kw):
        super().__init__(*a, **kw)
        self.cache = cache

    def file_response(self, *a, **kw) -> Response:
        resp = super().file_response(*a, **kw)
        resp.headers["Cache-Control"] = self.cache
        return resp


def static_version() -> str:
    return str(max(int(p.stat().st_mtime) for p in STATIC.rglob("*") if p.suffix in (".js", ".css")))


def canonical(path: str) -> str:
    return ALIASES.get(path, path)


async def index(request: Request) -> Response:
    # The entry module and stylesheet load from /static/v<newest mtime>/, so every relative import is versioned too:
    # a deploy changes every URL, and those URLs can be cached forever.
    v = static_version()
    html = (STATIC / "index.html").read_text()
    html = html.replace('"/static/app.js"', f'"/static/v{v}/app.js"').replace('"/static/style.css"', f'"/static/v{v}/style.css"')
    # index.html's canonical and og:url name the root; every SPA route serves it, so point them at this page.
    html = html.replace(f'"{SITE}/"', f'"{SITE}{canonical(request.url.path)}"')
    return HTMLResponse(html, headers={"Cache-Control": "no-cache"})


async def robots(_: Request) -> Response:
    return PlainTextResponse(f"User-agent: *\nAllow: /\nSitemap: {SITE}/sitemap.xml\n")


async def sitemap(_: Request) -> Response:
    """The top bar's pages and every doc."""
    nav = re.search(r'<nav id="nav">.*?</nav>', (STATIC / "index.html").read_text(), re.S)[0]
    paths = ["/", *(canonical(p) for p in re.findall(r'href="([^"]+)"', nav)), *(f"/docs/{d['name']}" for d in docs.listing())]
    urls = "".join(f"<url><loc>{SITE}{p}</loc></url>" for p in dict.fromkeys(paths))
    return Response(f'<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">{urls}</urlset>\n',
                    media_type="application/xml")


async def slippilab(_: Request) -> Response:
    return FileResponse(SLIPPILAB / "index.html", headers={"Cache-Control": "no-cache"})


async def hls(request: Request) -> Response:
    """Same-origin proxy for mediamtx LL-HLS (blocking playlist reloads included: query strings pass through)."""
    url = HLS_UPSTREAM + request.path_params["path"] + (f"?{request.url.query}" if request.url.query else "")
    headers = {k: v for k, v in request.headers.items() if k in ("cookie", "range", "user-agent")}
    try:
        r = await _hls.send(_hls.build_request("GET", url, headers=headers), stream=True)
    except httpx.HTTPError as e:
        return PlainTextResponse(f"live stream unavailable: {type(e).__name__}", status_code=502)
    resp = StreamingResponse(r.aiter_raw(), status_code=r.status_code, background=BackgroundTask(r.aclose))
    for k in ("content-type", "cache-control", "content-length", "content-range"):
        if k in r.headers:
            resp.headers[k] = r.headers[k]
    if "location" in r.headers:
        resp.headers["location"] = r.headers["location"].replace("/live/", "/hls/", 1)
    for c in r.headers.get_list("set-cookie"):
        resp.raw_headers.append((b"set-cookie", c.encode()))
    return resp


# --------------------------------------------------------------------------- API: launcher and jobs

async def api_catalog(request: Request) -> Response:
    cat = await blocking(specs.catalog)
    return ok(cat if await admin(request) else specs.public_catalog(cat))


def _job_view(j: dict) -> dict:
    return {**j, "label1": specs.label(j["p1"]), "label2": specs.label(j["p2"]),
            "char1_name": specs.char_name(j["char1"]), "char2_name": specs.char_name(j["char2"]),
            "stage_name": specs.stage_name(j["stage"]),
            "game_ids": [games.game_id(Path(r["replay"])) if r.get("replay") else None for r in j["results"]]}


async def api_jobs(request: Request) -> Response:
    if request.method == "GET":
        rows = await blocking(jobs.listing, int(request.query_params.get("limit", 100)))
        return ok({"jobs": [_job_view(j) for j in rows], "arena": await blocking(jobs.setting, "arena", "on")})
    body = await request.json()
    spec = {"p1": str(body.get("p1", "")).strip(), "p2": str(body.get("p2", "")).strip(),
            "char1": body.get("char1", "FOX"), "char2": body.get("char2", "FOX"), "stage": body.get("stage", "BATTLEFIELD"),
            "mode": body.get("mode", "lockstep"), "games": int(body.get("games", 1)), "preempt": int(bool(body.get("preempt")))}
    errors, warnings = await blocking(specs.validate, spec["p1"], spec["p2"], spec["char1"], spec["char2"],
                                      spec["stage"], spec["mode"], spec["games"])
    if not await admin(request):
        spec["preempt"] = 0
        waiting = sum(j["status"] == "queued" for j in await blocking(jobs.listing, 0))
        errors += specs.public_errors(spec, waiting)
    if errors:
        return ok({"errors": errors, "warnings": warnings}, 400)
    if body.get("dry_run"):
        return ok({"errors": [], "warnings": warnings})
    job = await blocking(jobs.add, spec)
    return ok({"job": _job_view(job), "warnings": warnings}, 201)


async def api_job(request: Request) -> Response:
    j = await blocking(jobs.get, int(request.path_params["id"]))
    if not j:
        return ok({"error": "no such job"}, 404)
    out = Path(j["dir"]) / "output.log"
    tail = ""
    if out.exists():
        with out.open("rb") as f:
            f.seek(max(0, out.stat().st_size - 6000))
            tail = f.read().decode(errors="replace")
    return ok({**_job_view(j), "output_tail": tail})


async def api_job_cancel(request: Request) -> Response:
    j = await blocking(jobs.cancel, int(request.path_params["id"]))
    return ok(_job_view(j)) if j else ok({"error": "no such job"}, 404)


async def api_settings(request: Request) -> Response:
    if request.method == "POST":
        body = await request.json()
        for key in ("arena", "commentator"):
            if key in body:
                await blocking(jobs.set_setting, key, "on" if body[key] else "off")
    return ok({"arena": await blocking(jobs.setting, "arena", "on") == "on",
               "commentator": await blocking(jobs.setting, "commentator", "off") == "on"})


async def api_me(request: Request) -> Response:
    return ok({"admin": await admin(request)})


async def login(request: Request) -> Response:
    """Cloudflare Access guards this path only: keep the JWT it sends as our own cookie, valid as long as the JWT."""
    nxt = request.query_params.get("next", "/")
    resp = RedirectResponse(nxt if nxt.startswith("/") and not nxt.startswith("//") else "/", status_code=303)
    token = request.headers.get("cf-access-jwt-assertion")
    claims = token and await blocking(auth.verify, token)
    if claims:
        resp.set_cookie(auth.COOKIE, token, max_age=max(0, int(claims["exp"] - time.time())), httponly=True, secure=True,
                        samesite="lax")
    return resp


async def logout(_: Request) -> Response:
    resp = RedirectResponse("/cdn-cgi/access/logout", status_code=303)
    resp.delete_cookie(auth.COOKIE)
    return resp


# --------------------------------------------------------------------------- API: live

async def api_live(_: Request) -> Response:
    return ok({"status": registry.live_status(await blocking(registry.snapshot)), "server_time": time.time()})


async def api_live_listen(_: Request) -> Response:
    """Heartbeat from a Live page with the voice on: the commentator speaks only while one is fresh."""
    VOICE_HEARTBEAT.parent.mkdir(parents=True, exist_ok=True)
    VOICE_HEARTBEAT.touch()
    return ok({"ok": True})


async def api_live_audio(request: Request) -> Response:
    """A commentary clip: only .mp3 files inside a <log>.audio folder under the replays or data dirs."""
    p = Path(request.query_params.get("p", "")).resolve()
    allowed = any(p.is_relative_to(root.resolve()) for root in (REPLAYS, DATA))
    if not (allowed and p.suffix == ".mp3" and p.parent.name.endswith(".audio") and p.is_file()):
        return ok({"error": "not found"}, 404)
    return FileResponse(p, media_type="audio/mpeg", headers={"Cache-Control": "max-age=86400"})


def _sse(event: str, data) -> bytes:
    return f"event: {event}\ndata: {json.dumps(data, default=str)}\n\n".encode()


class Tail:
    def __init__(self, path: str, port: int, kind: str):
        self.path, self.port, self.kind, self.buf = path, port, kind, ""
        self.f = open(path)

    def lines(self) -> list[dict]:
        self.buf += self.f.read()
        *complete, self.buf = self.buf.split("\n")
        out = []
        for ln in complete:
            try:
                out.append(json.loads(ln))
            except ValueError:
                pass
        return out


async def api_live_events(request: Request) -> Response:
    """SSE: `status` whenever the live slot's match (registry.live_status) changes, `log` for every decision-log line of the live game.

    Every event carries the wall-clock time it happened (`ts`); the page holds events back until the
    video (whose HLS segments carry EXT-X-PROGRAM-DATE-TIME from the same clock) has played that far.
    """
    async def stream():
        yield _sse("hello", {"server_time": time.time()})
        last, tails, ping = None, {}, time.time()
        try:
            while not await request.is_disconnected():
                st = registry.live_status(await blocking(registry.snapshot))
                key = json.dumps({k: v for k, v in st.items() if k != "updated"}, sort_keys=True, default=str)
                if key != last:
                    last = key
                    yield _sse("status", st)
                current = {lg["path"]: lg for lg in st.get("logs") or []}
                for path, lg in current.items():
                    if path not in tails:
                        try:
                            tails[path] = Tail(path, lg["port"], lg["kind"])
                        except OSError:
                            continue
                for path, t in list(tails.items()):
                    for rec in t.lines():
                        yield _sse("log", {"port": t.port, "kind": t.kind, "rec": logs.slim(rec)})
                    if path not in current:
                        t.f.close()
                        del tails[path]
                if time.time() - ping > 15:
                    ping = time.time()
                    yield b": ping\n\n"
                await asyncio.sleep(0.2)
        finally:
            for t in tails.values():
                t.f.close()

    return StreamingResponse(stream(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


# --------------------------------------------------------------------------- API: all matches (registry)

def _no_ring(m: dict) -> dict:
    return {k: v for k, v in m.items() if k != "ring"}


async def api_matches(_: Request) -> Response:
    return ok({"matches": [_no_ring(m) for m in await blocking(registry.snapshot)], "server_time": time.time()})


async def api_matches_events(request: Request) -> Response:
    """SSE over the match registry: `match` (status without frames, at most every 0.5 s per match or on a phase
    change), `frames` {id, frames: samples newer than the last ones sent} and `gone` {id}. `?id=` follows one."""
    only = request.query_params.get("id")

    async def stream():
        yield _sse("hello", {"server_time": time.time()})
        sent: dict[str, tuple[float, str]] = {}  # id → (when the status went out, phase)
        last_frame: dict[str, int] = {}
        ping = time.time()
        while not await request.is_disconnected():
            ms = [m for m in await blocking(registry.snapshot) if not only or m["id"] == only]
            now = time.time()
            for m in ms:
                mid = m["id"]
                prev = sent.get(mid)
                if prev is None or prev[1] != m.get("phase") or (now - prev[0] >= 0.5 and m.get("phase") not in registry.ENDED):
                    sent[mid] = (now, m.get("phase"))
                    yield _sse("match", _no_ring(m))
                new = [f for f in m.get("ring") or [] if f[0] > last_frame.get(mid, -10**9)]
                if new and m.get("phase") not in registry.ENDED:
                    last_frame[mid] = new[-1][0]
                    yield _sse("frames", {"id": mid, "frames": new})
            for mid in set(sent) - {m["id"] for m in ms}:
                sent.pop(mid, None)
                last_frame.pop(mid, None)
                yield _sse("gone", {"id": mid})
            if now - ping > 15:
                ping = now
                yield b": ping\n\n"
            await asyncio.sleep(0.1)

    return StreamingResponse(stream(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


# --------------------------------------------------------------------------- API: results

async def api_games(request: Request) -> Response:
    q = request.query_params
    return ok(await blocking(games.query, q.get("q", ""), q.get("source", ""), q.get("mode", ""), q.get("char", ""),
                             q.get("stage", ""), q.get("since", ""), q.get("until", ""), q.get("logs") == "1",
                             min(int(q.get("limit", 100)), 500), int(q.get("offset", 0))))


async def api_game(request: Request) -> Response:
    g = await blocking(games.game_detail, request.path_params["id"])
    return ok(g) if g else ok({"error": "no such game"}, 404)


async def api_replay(request: Request) -> Response:
    g = await blocking(games.INDEX.find, request.path_params["id"])
    if not g or not Path(g["path"]).exists():
        return PlainTextResponse("no such replay", status_code=404)
    return FileResponse(g["path"], media_type="application/octet-stream")


async def api_arena(_: Request) -> Response:
    return ok(await blocking(games.arena))


async def api_coach(_: Request) -> Response:
    return ok(await blocking(games.coach_pilots))


async def api_sessions(_: Request) -> Response:
    return ok(await blocking(games.botwriter_sessions))


async def api_session(request: Request) -> Response:
    s = await blocking(games.botwriter_session, request.path_params["id"])
    return ok(s) if s else ok({"error": "no such session"}, 404)


async def api_ladders(_: Request) -> Response:
    return ok(await blocking(games.ladders))


async def api_bench(_: Request) -> Response:
    from melee_llm.bench import views
    return ok(await blocking(views.board))


async def api_bench_entrant(request: Request) -> Response:
    from melee_llm.bench import views
    e = await blocking(views.entrant, request.path_params["id"])
    return ok(e) if e else ok({"error": "no such entrant"}, 404)


async def api_training(_: Request) -> Response:
    return ok({"runs": await blocking(training.runs), "server_time": time.time()})


async def api_netplay(_: Request) -> Response:
    return ok({"sessions": [], "note": "netplay is not wired up yet"})


async def api_docs(_: Request) -> Response:
    return ok(await blocking(docs.listing))


async def api_docs_search(request: Request) -> Response:
    return ok(await blocking(docs.search, request.query_params.get("q", "")))


async def api_doc(request: Request) -> Response:
    d = await blocking(docs.render, request.path_params["name"])
    return ok(d) if d else ok({"error": "no such doc"}, 404)


SPA = ["/", "/bench", "/bench/{id:path}", "/live", "/matches", "/matches/{id}", "/launch", "/jobs", "/job/{id}", "/games", "/game/{id}", "/arena", "/coach", "/botwriter",
       "/botwriter/{id}", "/ladder/{name}", "/play", "/training", "/brute", "/docs", "/docs/{name}"]

routes = [
    *[Route(p, index) for p in SPA],
    Route("/robots.txt", robots),
    Route("/sitemap.xml", sitemap),
    Route("/login", login),
    Route("/logout", logout),
    Route("/api/me", api_me),
    Route("/slippilab/", slippilab),
    Route("/hls/{path:path}", hls),
    Route("/api/catalog", api_catalog),
    Route("/api/jobs", api_jobs, methods=["GET", "POST"]),
    Route("/api/jobs/{id:int}", api_job),
    Route("/api/jobs/{id:int}/cancel", operator_only(api_job_cancel), methods=["POST"]),
    Route("/api/settings", operator_only(api_settings), methods=["GET", "POST"]),
    Route("/api/live", api_live),
    Route("/api/live/events", api_live_events),
    Route("/api/live/listen", operator_only(api_live_listen), methods=["POST"]),
    Route("/api/live/audio", api_live_audio),
    Route("/api/matches", api_matches),
    Route("/api/matches/events", api_matches_events),
    Route("/api/games", api_games),
    Route("/api/games/{id}", api_game),
    Route("/api/replay/{id}/{name}", api_replay),
    Route("/api/arena", api_arena),
    Route("/api/coach", api_coach),
    Route("/api/botwriter/sessions", api_sessions),
    Route("/api/botwriter/sessions/{id}", api_session),
    Route("/api/ladders", api_ladders),
    Route("/api/bench", api_bench),
    Route("/api/bench/entrant/{id:path}", api_bench_entrant),
    Route("/api/training", api_training),
    Route("/api/netplay", api_netplay),
    Route("/api/docs", api_docs),
    Route("/api/docs/search", api_docs_search),
    Route("/api/docs/{name}", api_doc),
    # Any version serves the current files; a stale version in a cached index.html then still gets working code.
    Mount("/static/v{version:int}", CachedStatic(directory=STATIC, cache="public, max-age=31536000, immutable")),
    Mount("/static", CachedStatic(directory=STATIC, cache="no-cache")),
    # The write-up is a standalone page (writeup/build_page.py) with relative figure and media links
    Route("/writeup", lambda _: RedirectResponse("/writeup/", status_code=308)),
    Mount("/writeup", CachedStatic(directory=ROOT / "writeup", html=True, check_dir=False, cache="no-cache")),
    # Slippi Lab's build references its assets from the site root
    Mount("/assets", StaticFiles(directory=SLIPPILAB / "assets", check_dir=False)),
    Mount("/zips", StaticFiles(directory=SLIPPILAB / "zips", check_dir=False)),
    *[Route(f"/{n}", (lambda n: lambda _: FileResponse(SLIPPILAB / n))(n)) for n in ("favicon.ico", "logo.png", "logo-square.png")],
    Route("/slippilab-live.js", lambda _: FileResponse(SLIPPILAB / "live-renderer.js", media_type="text/javascript",
                                                        headers={"Cache-Control": "no-cache"})),
]

app = Starlette(routes=routes)


def main() -> None:
    host = os.environ.get("BIND", "127.0.0.1")
    if host in ("0.0.0.0", "::"):
        raise SystemExit("refusing to bind all interfaces; requests that do not come through Cloudflare count as the owner")
    uvicorn.run(app, host=host, port=int(os.environ.get("PORT", "8770")), log_level="warning", proxy_headers=True)


if __name__ == "__main__":
    main()
