"""Play on stomped.dev: a WebSocket server that reads the .slp event stream and answers 12-byte pads.

    uv run python -m meleebot.stomped CHECKPOINT --url https://HOST/SECRET [--port 3000]

Spec: https://docs.stomped.dev/llms-full.txt. stomped connects to the registered URL when a match
starts; `GET <url>/ping` must answer `pong`. Upgrades are checked against stomped's Ed25519
signature over the registered URL (--no-verify for local tests).

Timing: having seen frame F, the first pad still open is for F + 1 + inputDelayFrames, due 11 ms
after F was sent. A pad for a later frame lands as long as it arrives before that frame is polled, so
a bot with a long round trip aims further ahead: `lead` frames past F. The model was trained for
exactly that (features.py): a token sees its own pads up to t and the game state of t - delay, and
picks the pad for t + 1. Here t + 1 = F + lead, so delay = lead - 1, and the pads for F + 1 .. t are the
ones this bot already sent.
"""
import argparse, asyncio, base64, http, json, math, os, struct, time
from collections import deque
from urllib.parse import urlsplit

import numpy as np
import torch

from . import features as fe
from .model import check_rank, default_rank, load
from .play import RawFrames
from .schema import BUTTONS, CHARACTERS, FRAME, RANKS

YOSHI = CHARACTERS.index("YOSHI")
STAGE_OF = {i: s for s, i in fe.STAGE_INDEX.items()}
EVENT_PAYLOADS, GAME_START, PRE_FRAME, POST_FRAME, GAME_END, FRAME_BOOKEND = 0x35, 0x36, 0x37, 0x38, 0x39, 0x3C
FRAME_MS, BUDGET_MS = 1000 / 60, 11.0
_PAD = FRAME["me_pad"]
NEUTRAL = np.zeros((), _PAD)
# Button classes (features.BUTTON_GROUPS: A, B, Z, X|Y, L|R) -> the bit this bot presses for each.
_PRESS = [BUTTONS["A"], BUTTONS["B"], BUTTONS["Z"], BUTTONS["X"], BUTTONS["L"]]


class Events:
    """Incremental reader of the raw .slp event stream. Each event keeps its command byte, so its
    offsets match the Slippi spec (and play.RawFrames)."""

    def __init__(self):
        self.sizes = {}

    def feed(self, msg: bytes):
        i = 0
        while i < len(msg):
            cmd = msg[i]
            if cmd == EVENT_PAYLOADS:
                n = msg[i + 1]
                self.sizes = {msg[j]: struct.unpack_from(">H", msg, j + 1)[0] for j in range(i + 2, i + 1 + n, 3)}
                i += 1 + n
                continue
            size = self.sizes.get(cmd)
            if size is None:  # unknown command: the rest of the message cannot be framed
                return
            yield cmd, msg[i:i + 1 + size]
            i += 1 + size


def choice_to_pad(choice, centers):
    """Model classes -> a CONTROLLER record in dataset units (what features.pad_num reads back)."""
    c = np.zeros((), _PAD)
    c["stick"] = centers[int(choice["stick"])]
    k = int(choice["cstick"])
    c["cstick"] = np.round(fe.CSTICK_DIRS[k - 1] * 80) if k else (0, 0)
    bits = int(choice["buttons"])
    buttons = sum(bit for i, bit in enumerate(_PRESS) if bits >> i & 1)
    c["buttons"] = buttons
    c["trigger"] = (140 if buttons & BUTTONS["L"] else fe.SHOULDER_LEVELS[int(choice["shoulder"])], 0)
    return c


def wire(frame: int, c) -> bytes:
    """CONTROLLER record -> stomped's pad: i32 frame, u16 buttons, sticks 0-255 (centre 128), L, R."""
    sx, sy = (int(v) + 128 for v in c["stick"])
    cx, cy = (int(v) + 128 for v in c["cstick"])
    l, r = (int(v) for v in c["trigger"])
    return struct.pack("<iH6B", frame, int(c["buttons"]), sx, sy, cx, cy, l, r)


class Brain:
    """The model, one match at a time. `decide(F)` returns (frame, pad record) for frame F + lead."""

    def __init__(self, checkpoint, device=None, rank=None, win=1, temperature=1.0, threads=4):
        self.device = device or ("cuda" if torch.cuda.is_available() else "cpu")
        torch.set_num_threads(threads)
        self.model, self.ckpt = load(checkpoint, self.device)
        self.centers = self.model.stick_centers.cpu().numpy().astype(np.int64)
        self.cached = self.model.config.pos == "rope"
        self.context = self.model.config.context
        rank = rank or default_rank(self.ckpt)
        check_rank(self.ckpt, rank)
        self.rank, self.win, self.temperature = RANKS.index(rank), {0: 0, 1: 1, None: 2}[win], temperature

    def new_match(self, port, me_char, opp_char, stage, lead):
        self.port, self.opp = port, 1 - port
        self.cond = dict(me_char=me_char, opp_char=opp_char, stage=fe.STAGE_INDEX[stage], rank=self.rank, win=self.win)
        self.set_lead(lead)
        self.raw = {}          # (frame, port) -> player record, and ("pad", frame, port) -> pad record
        self.sent = {}         # frame -> pad record this bot sent for it
        self.tokens = deque(maxlen=self.context)
        self.caches, self.n = (self.model.new_caches() if self.cached else None), 0

    def warmup(self, n=300):
        """Run the model on dummy frames, so the first real decisions aren't slowed by first-call setup."""
        f = np.zeros((), FRAME)
        for i in range(n):
            self.raw[(i, self.port)] = self.raw[(i, self.opp)] = f["me"]
            self.raw[("pad", i, self.opp)] = f["opp_pad"]
            self.decide(i)
        self.new_match(self.port, self.cond["me_char"], self.cond["opp_char"], STAGE_OF[self.cond["stage"]], self.lead)

    def set_lead(self, lead):
        self.lead = max(2, min(int(lead), fe.MAX_DELAY + 1))
        self.delay = self.lead - 1

    def on_event(self, cmd, b):
        if cmd in (PRE_FRAME, POST_FRAME) and b[0x6] == 0:  # leaders only (no Nana)
            frame, port = struct.unpack_from(">i", b, 1)[0], b[0x5]
            if cmd == POST_FRAME:
                self.raw[(frame, port)] = RawFrames._player(b)
            else:
                self.raw[("pad", frame, port)] = RawFrames._pad(b)

    def polled(self, frame):
        """The pad the game read for this bot at `frame`, from the stream (None if not seen)."""
        return self.raw.get(("pad", frame, self.port))

    @torch.inference_mode()
    def decide(self, F):
        """After frame F's bookend: the pad for F + lead, or None before play starts."""
        me, opp, opp_pad = self.raw.get((F, self.port)), self.raw.get((F, self.opp)), self.raw.get(("pad", F, self.opp))
        for k in [k for k in self.raw if (k[1] if k[0] == "pad" else k[0]) < F - 2]:
            del self.raw[k]
        if F < 0 or me is None or opp is None or opp_pad is None:
            return None
        f = np.zeros((), FRAME)
        f["me"], f["opp"], f["opp_pad"] = me, opp, opp_pad
        state, _, opp_num, actions = fe.frame_parts(f[None], self.model.config.features)
        t = F + self.lead - 1
        own = fe.pad_num(self.sent.get(t, NEUTRAL)[None])
        self.tokens.append((np.concatenate([state[0], own[0], opp_num[0]]), actions[0]))
        b = self._batch(1 if self.cached else len(self.tokens))
        with torch.autocast(self.device, torch.bfloat16, enabled=self.device == "cuda"):
            if self.cached:
                choice = self.model.step(b, self.n, self.caches, self.temperature)
                self.n += 1
            else:
                choice = self.model.sample(b, self.temperature)
        pad = choice_to_pad({k: v.item() for k, v in choice.items()}, self.centers)
        self.sent[t + 1] = pad
        self.sent.pop(t - 2 * self.context, None)
        return t + 1, pad

    def _batch(self, T):
        num = np.stack([x for x, _ in list(self.tokens)[-T:]])[None]
        act = np.stack([a for _, a in list(self.tokens)[-T:]])[None]
        b = dict(num=num, actions=act, delay=[self.delay], **{k: [v] for k, v in self.cond.items()})
        return {k: torch.as_tensor(np.asarray(v), device=self.device) for k, v in b.items()}


def lead_for(rtt_ms, compute_ms, input_delay=1):
    """Smallest lead whose pad still arrives in time: the pad for F + 1 + inputDelay + k is due
    11 ms + k frames after F is sent, and needs a round trip plus the compute to get there."""
    return 1 + input_delay + max(0, math.ceil((rtt_ms + compute_ms - BUDGET_MS) / FRAME_MS))


class Match:
    def __init__(self, bot, ws):
        self.bot, self.ws, self.brain = bot, ws, bot.brain
        self.events, self.started, self.compute = Events(), False, []
        self.step, self.late, self.lead_changes = {}, deque(maxlen=120), []
        self.t0 = time.time()

    async def rtt(self, n=5):
        """WebSocket ping round trips, in ms; the worst one counts."""
        out = []
        for _ in range(n):
            t = time.perf_counter()
            await (await self.ws.ping())
            out.append((time.perf_counter() - t) * 1000)
        return max(out)

    async def text(self, step):
        self.step = step
        s = step["step"]
        if s == "character":
            await self.ws.send(json.dumps({"step": "character", "character": YOSHI, "costume": self.bot.costume}))
            self.rtt_ms = await self.rtt()
        elif s == "ready":
            self.start(step)  # warms the model up first: the game may start right after this reply
            await self.ws.send(json.dumps({"step": "ready"}))
        elif s == "game":
            if not self.started:
                self.start(step)
            # the frame names the last finished frame: cover the next pads with neutral now
            for f in range(step["frame"] + 1, step["frame"] + 1 + self.brain.lead):
                await self.ws.send(wire(f, self.brain.sent.get(f, NEUTRAL)))
            if step["frame"] > -124 and not self.events.sizes:
                await self.ws.send(json.dumps({"step": "replay"}))
        elif s == "over":
            self.bot.log(dict(self.summary(), winner=step.get("winner"), endReason=step.get("endReason"),
                              missed=step.get("missed")))

    def start(self, step):
        players = step["players"]
        me, opp = step["port"], 1 - step["port"]
        rtt = getattr(self, "rtt_ms", None)
        lead = self.bot.lead or lead_for(rtt if rtt is not None else 150, self.bot.compute_ms, step["inputDelayFrames"])
        self.brain.new_match(me, players[me]["character"], players[opp]["character"], step["stage"], lead)
        self.brain.warmup(60)
        self.started = True
        print(f"match {step['matchId']} vs {step['opponent']['name']}: port {me}, stage {step['stage']}, "
              f"opponent {CHARACTERS[players[opp]['character']]}, rtt {rtt} ms, lead {self.brain.lead}", flush=True)

    async def binary(self, msg: bytes):
        if not self.started:
            return
        if not self.events.sizes and msg[:1] != bytes([EVENT_PAYLOADS]):
            return  # after a reconnect: wait for the replay, which starts with the header
        last = None
        for cmd, b in self.events.feed(msg):
            self.brain.on_event(cmd, b)
            if cmd == FRAME_BOOKEND:
                last = struct.unpack_from(">i", b, 1)[0]
        if last is None:
            return
        t = time.perf_counter()
        out = self.brain.decide(last)
        if out is None:  # before play starts: neutral, so the frame is not counted as missed
            await self.ws.send(wire(last + self.brain.lead, NEUTRAL))
        else:
            frame, pad = out
            await self.ws.send(wire(frame, pad))
            self.compute.append((time.perf_counter() - t) * 1000)
        self.check_late(last)

    def check_late(self, F):
        """The stream shows what the game read for us: a pressed pad read as fully neutral arrived late
        (sticks are compared after the game's dead zone, so only all-neutral counts). If that happens
        often, aim one frame further ahead."""
        sent, read = self.brain.sent.get(F), self.brain.polled(F)
        if self.bot.lead or sent is None or read is None or sent["buttons"] == 0:
            return
        self.late.append(bool(read["buttons"] == 0 and not read["stick"].any() and not read["trigger"].any()))
        if len(self.late) == self.late.maxlen and sum(self.late) > 6 and self.brain.lead <= fe.MAX_DELAY:
            self.brain.set_lead(self.brain.lead + 1)
            self.lead_changes.append((F, self.brain.lead))
            self.late.clear()

    def summary(self):
        c = sorted(self.compute) or [0]
        return dict(matchId=self.step.get("matchId"), opponent=self.step.get("opponent"), stage=self.step.get("stage"),
                    players=self.step.get("players"), port=self.step.get("port"), rtt_ms=getattr(self, "rtt_ms", None),
                    lead=self.brain.lead if self.started else None, lead_changes=self.lead_changes, decisions=len(self.compute),
                    compute_p50=round(c[len(c) // 2], 2), compute_p95=round(c[int(len(c) * .95)], 2),
                    seconds=round(time.time() - self.t0))


class Bot:
    def __init__(self, a):
        self.brain = Brain(a.checkpoint, a.device, a.rank, temperature=a.temperature, threads=a.threads)
        self.url, self.verify, self.costume, self.lead = a.url, not a.no_verify, a.costume, a.lead
        self.path = urlsplit(a.url).path.rstrip("/") or "/"
        self.compute_ms = a.compute_ms
        self.log_path, self.busy = a.log, False
        self.key = self.platform_key() if self.verify else None
        self.brain.new_match(0, YOSHI, CHARACTERS.index("FOX"), 31, 2)
        self.brain.warmup()

    def platform_key(self):
        from urllib.request import urlopen
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
        raw = json.load(urlopen("https://api.stomped.dev/.well-known/stomped.json", timeout=10))["publicKey"]
        return Ed25519PublicKey.from_public_bytes(base64.b64decode(raw))

    def signed(self, headers) -> bool:
        if not self.verify:
            return True
        try:
            ts, match, sig = headers["x-stomped-timestamp"], headers["x-stomped-match"], headers["x-stomped-signature"]
            if abs(time.time() * 1000 - int(ts)) > 30_000:
                return False
            self.key.verify(base64.b64decode(sig), f"{ts}.{match}.{self.url}".encode())
            return True
        except Exception:
            return False

    def log(self, row):
        print(json.dumps(row), flush=True)
        if self.log_path:
            with open(self.log_path, "a") as fh:
                fh.write(json.dumps(dict(row, time=time.time())) + "\n")

    def process_request(self, connection, request):
        path = request.path.split("?")[0].rstrip("/") or "/"
        if path == f"{self.path.rstrip('/')}/ping" or path == "/ping" and self.path == "/":
            return connection.respond(http.HTTPStatus.OK, "pong")
        if path != self.path:
            return connection.respond(http.HTTPStatus.NOT_FOUND, "not found")
        if not self.signed(request.headers):
            return connection.respond(http.HTTPStatus.UNAUTHORIZED, "bad signature")
        return None

    async def handler(self, ws):
        if ws.request.headers.get("x-stomped-match") == "deploy-check":
            return
        if self.busy:  # one match at a time; stomped never seats a bot twice
            await ws.close(1013, "busy")
            return
        self.busy = True
        m = Match(self, ws)
        try:
            async for msg in ws:
                if isinstance(msg, str):
                    await m.text(json.loads(msg))
                else:
                    await m.binary(msg)
        finally:
            self.busy = False
            if m.started and m.step.get("step") != "over":
                self.log(dict(m.summary(), disconnected=True))


async def serve(bot, host, port):
    from websockets.asyncio.server import serve as ws_serve
    async with ws_serve(bot.handler, host, port, process_request=bot.process_request, max_size=None,
                        compression=None, ping_interval=None):
        print(f"stomped bot on {host}:{port}{bot.path} ({bot.brain.device}, lead "
              f"{bot.lead or 'from rtt'}, signature check {'on' if bot.verify else 'OFF'})", flush=True)
        await asyncio.get_running_loop().create_future()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("checkpoint")
    ap.add_argument("--url", required=True, help="the registered URL, byte for byte (the handshake is signed over it)")
    ap.add_argument("--host", default="127.0.0.1"); ap.add_argument("--port", type=int, default=3000)
    ap.add_argument("--device"); ap.add_argument("--threads", type=int, default=4)
    ap.add_argument("--lead", type=int, help="frames to aim ahead, fixed; default: from the measured round trip, raised when pads land late")
    ap.add_argument("--compute-ms", type=float, default=5.0, help="expected decision time, for the lead")
    ap.add_argument("--rank", default=None, choices=RANKS, help="default: the model's most-trained rank"); ap.add_argument("--temperature", type=float, default=1.0)
    ap.add_argument("--costume", type=int, default=0)
    ap.add_argument("--log", default=os.path.expanduser("~/projects/ai/melee-llm/data/stomped/matches.jsonl"))
    ap.add_argument("--no-verify", action="store_true", help="accept unsigned upgrades (local tests only)")
    a = ap.parse_args()
    if a.log:
        os.makedirs(os.path.dirname(a.log), exist_ok=True)
    asyncio.run(serve(Bot(a), a.host, a.port))


if __name__ == "__main__":
    main()
