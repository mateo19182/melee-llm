"""A local stand-in for stomped's arena: streams a recorded .slp to a bot, as stomped would, and checks its pads.

    uv run python -m meleebot.stomped_arena REPLAY.slp ws://127.0.0.1:3000/SECRET [--port 0] [--rtt-ms 0]

The game is the recording, so the bot's pads don't change it: this tests the protocol, the parsing
and the timing, not the play. A pad counts as on time if it arrives before its frame is polled,
which stomped does 11 ms after sending the frame two before it (inputDelayFrames = 1). --rtt-ms
adds that much round trip (half each way) to imitate a bot far from the arena.
"""
import argparse, asyncio, json, struct, time

from .stomped import EVENT_PAYLOADS, FRAME_BOOKEND, GAME_END, BUDGET_MS, FRAME_MS

FRAME_START = 0x3A


def slp_messages(path):
    """A .slp file -> the binary messages stomped streams: header, one per frame (Frame Start to
    Frame Bookend), then Game End."""
    data = open(path, "rb").read()
    i = data.index(b"raw[$U#l") + 8
    raw = data[i + 4:i + 4 + struct.unpack(">I", data[i:i + 4])[0]]
    assert raw[0] == EVENT_PAYLOADS, hex(raw[0])
    n = raw[1]
    sizes = {raw[j]: struct.unpack_from(">H", raw, j + 1)[0] for j in range(2, 1 + n, 3)}
    out, start, pos = [], 0, 1 + n
    while pos < len(raw):
        cmd = raw[pos]
        end = pos + 1 + sizes[cmd]
        if cmd == FRAME_START and not out:
            out.append(raw[:pos]); start = pos
        elif cmd in (FRAME_BOOKEND, GAME_END):
            out.append(raw[start:end]); start = end
        pos = end
    return out


def _runs(xs):
    """[1, 2, 3, 7] -> "1-3, 7"."""
    out = []
    for x in xs:
        if out and x == out[-1][1] + 1:
            out[-1][1] = x
        else:
            out.append([x, x])
    return ", ".join(f"{a}-{b}" if a != b else str(a) for a, b in out)


def _frame_of(msg):
    """Frame number of a per-frame message (it starts with Frame Start: cmd, i32 frame)."""
    return struct.unpack_from(">i", msg, 1)[0]


async def run(path, url, port, rtt_ms, characters, stage, limit=None):
    from websockets.asyncio.client import connect
    msgs = slp_messages(path)
    header, frames = msgs[0], msgs[1:]
    if frames and frames[-1][0] == GAME_END:
        frames = frames[:-1]
    frames = frames[:limit]
    base = dict(version=1, matchId="local-test", mode="live", port=port, opponent=dict(botId="x", name="recording"),
                stage=stage, inputDelayFrames=1)
    pads, sent_at, late_wire = {}, {}, rtt_ms / 2000
    async with connect(url, max_size=None, compression=None, additional_headers={"x-stomped-match": "local-test"}) as ws:
        async def reader():
            async for m in ws:
                if isinstance(m, bytes):
                    if len(m) == 12:  # it would reach the arena half a round trip after it reached us
                        pads.setdefault(struct.unpack_from("<i", m)[0], time.perf_counter() + late_wire)
                else:
                    replies.put_nowait(json.loads(m))
        replies = asyncio.Queue()
        task = asyncio.create_task(reader())

        await ws.send(json.dumps(dict(base, step="character", sentAt=0, deadlineAt=0)))
        pick = await asyncio.wait_for(replies.get(), 5)
        players = [dict(character=c, costume=0) for c in characters]
        await ws.send(json.dumps(dict(base, step="ready", players=players, sentAt=0, deadlineAt=0)))
        ready = await asyncio.wait_for(replies.get(), 10)
        await ws.send(json.dumps(dict(base, step="game", players=players, frame=-124, sentAt=0)))
        await ws.send(header)
        wire = asyncio.Queue()  # frames reach the bot half a round trip after the arena sends them

        async def deliver():
            while (item := await wire.get()) is not None:
                due, m = item
                await asyncio.sleep(max(0, due - time.perf_counter()))
                await ws.send(m)
        courier = asyncio.create_task(deliver())
        tick = time.perf_counter()
        for m in frames:
            tick += FRAME_MS / 1000
            await asyncio.sleep(max(0, tick - time.perf_counter()))
            sent_at[_frame_of(m)] = now = time.perf_counter()
            wire.put_nowait((now + late_wire, m))
        wire.put_nowait(None)
        await courier
        await asyncio.sleep(0.2)
        await ws.send(json.dumps(dict(base, step="over", players=players, winner=None, endReason="time", missed=[0, 0])))
        await asyncio.sleep(0.1)
        task.cancel()

    # Frame x is polled 11 ms after frame x - 2 was sent; whatever lead the bot uses, its pad for x
    # must be there by then.
    landed, margins, missed = 0, [], []
    for f in sorted(sent_at):
        x = f + 2
        if x in pads and pads[x] <= sent_at[f] + BUDGET_MS / 1000:
            landed += 1
            margins.append((sent_at[f] + BUDGET_MS / 1000 - pads[x]) * 1000)
        else:
            missed.append(x)
    margins.sort()
    return dict(pick=pick, ready=ready, frames=len(sent_at), pads=len(pads), landed=landed,
                missed=len(missed), missed_frames=_runs(missed),
                margin_ms_p5=round(margins[len(margins) // 20], 2) if margins else None,
                margin_ms_p50=round(margins[len(margins) // 2], 2) if margins else None)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("replay"); ap.add_argument("url")
    ap.add_argument("--port", type=int, default=0, help="which recorded player the bot is")
    ap.add_argument("--rtt-ms", type=float, default=0)
    ap.add_argument("--characters", type=int, nargs=2, default=[17, 2], help="external ids by port (picks shown to the bot)")
    ap.add_argument("--stage", type=int, default=31)
    ap.add_argument("--frames", type=int, help="stream only this many frames")
    a = ap.parse_args()
    print(json.dumps(asyncio.run(run(a.replay, a.url, a.port, a.rtt_ms, a.characters, a.stage, a.frames)), indent=1))


if __name__ == "__main__":
    main()
