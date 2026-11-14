"""Sandbox tools: `practice` plays real games (needs the ISO, or with --sim the simulator's data extracted from
it); `check` replays recorded games through the bot offline to catch crashes and slow frames.

  python -m melee_llm.botwriter.practice play  --bot bot.py --opponent cpu:7 --games 5
  python -m melee_llm.botwriter.practice play  --bot bot.py --opponent baseline:rusher --games 20 --sim
  python -m melee_llm.botwriter.practice check --bot bot.py [--replay x.slp]
"""
from __future__ import annotations

import argparse
import json
import multiprocessing as mp
import time
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import melee

from melee_llm.botwriter.agent import BotAgent
from melee_llm.botwriter.dolphin import claim_slippi_port, exit_on_term, find_iso
from melee_llm.botwriter.host import FakeController
from melee_llm.botwriter.specs import make_agent
from melee_llm.botwriter.summary import GameSummary, compact, summarize
from melee_llm.paths import REPLAYS
from melee_llm.runner import play, replay_states
from melee_llm.sim import world

STAGES = {"fd": melee.Stage.FINAL_DESTINATION, "bf": melee.Stage.BATTLEFIELD,
          "FINAL_DESTINATION": melee.Stage.FINAL_DESTINATION, "BATTLEFIELD": melee.Stage.BATTLEFIELD}
PRACTICE_SPECS = ("cpu:N (1-9)", "idle", "baseline:NAME", "bot:PATH", "self")


def _opponent(spec: str, bot: Path, char: melee.Character, budget, log_dir: Path):
    if spec == "self":
        spec = f"bot:{bot}"
    if spec.startswith("agent:"):
        raise SystemExit(f"opponent {spec!r} is not available in practice; use one of {PRACTICE_SPECS}")
    return make_agent(spec, char, budget, log_dir, allow_agents=False)


def _play_side(bot: Path, opponent: str, bot_port: int, n: int, stage: melee.Stage, iso: str | None, out: Path,
               opp_char: melee.Character, budget_ms: float | None, mode: str) -> list[dict]:
    exit_on_term()
    rdir = out / f"port{bot_port}"
    opp = _opponent(opponent, bot, opp_char, budget_ms, out)
    me = BotAgent(bot, budget_ms, log_path=out / f"bot-port{bot_port}.log")
    summaries, live = [], None

    def observe(event: str, info: dict) -> None:  # the simulator writes no replay: summarize as it plays
        nonlocal live
        if event == "game_start":
            live = GameSummary()
        if event in ("frame", "game_end"):
            live.add(info["gs"])
        if event == "game_end":
            summaries.append(live.result())

    sim = mode == "sim"
    results = play({bot_port: me, 3 - bot_port: opp}, iso, stage, mode=mode, games=n, replay_dir=rdir,
                   slippi_port=0 if sim else claim_slippi_port(), observer=observe if sim else None)
    games = []
    for i, r in enumerate(results):
        g = {"bot_port": bot_port, "winner": r.winner, "result": "draw" if r.winner is None else
             "win" if r.winner == bot_port else "loss", "stocks": {p: int(v) for p, v in r.stocks.items()},
             "percent": {p: round(float(v), 1) for p, v in r.percent.items()}, "frames": r.frames,
             "seconds": round(r.seconds, 1), "bot_frame_stats": me.game_stats[i] if i < len(me.game_stats) else None}
        if sim:
            g["summary"] = summaries[i]
        elif r.replay:
            g["replay"] = r.replay
            try:
                g["summary"] = summarize(r.replay)
            except Exception as e:  # a broken replay must not hide the result
                g["summary_error"] = str(e)
        games.append(g)
    return games


def run_practice(bot: Path, opponent: str, games: int, stage: melee.Stage, iso: str | None, out: Path,
                 opp_char: melee.Character = melee.Character.FOX, budget_ms: float | None = 16.0,
                 mode: str = "fast") -> dict:
    """Games alternate spawn sides; the two sides run at once in their own Dolphins (or simulators)."""
    out.mkdir(parents=True, exist_ok=True)
    opp = _opponent(opponent, bot, opp_char, budget_ms, out)  # reject bad specs before starting Dolphins
    opp.close()
    if mode == "sim" and opp.cpu_level:
        raise SystemExit("the simulator has no in-game CPUs: practice against CPUs without --sim")
    exit_on_term()
    report = {"bot": str(bot), "opponent": opponent, "stage": stage.name, "games": []}
    sides = [(p, n) for p, n in ((1, (games + 1) // 2), (2, games // 2)) if n]
    with ProcessPoolExecutor(len(sides), mp_context=mp.get_context("spawn")) as pool:
        futs = [pool.submit(_play_side, bot, opponent, p, n, stage, iso, out, opp_char, budget_ms, mode) for p, n in sides]
        for f in futs:
            report["games"] += f.result()
    res = [g["result"] for g in report["games"]]
    report["record"] = {"wins": res.count("win"), "losses": res.count("loss"), "draws": res.count("draw")}
    report["stock_diff_avg"] = round(sum(
        g["stocks"][g["bot_port"]] - g["stocks"][3 - g["bot_port"]] for g in report["games"]) / max(1, len(res)), 2)
    (out / "report.json").write_text(json.dumps(report, indent=1, default=float))
    return report


def check(bot: Path, replays: list[Path], budget_ms: float | None, max_frames: int) -> dict:
    """Feed recorded frames to the bot as if it were playing one of the ports."""
    agent = BotAgent(bot, budget_ms)
    t0, frames, pressed = time.time(), 0, 0
    try:
        for slp in replays:
            ports = None
            for gs in replay_states(slp):
                if ports is None:
                    ports = sorted(int(p) for p in gs.players)
                    agent.setup(FakeController(ports[0]), ports[0], ports[1])
                if agent.pending is not None:
                    time.sleep(1 / 60)  # a busy bot catches up at real-time pace, as in a live match
                agent.step(gs)
                frames += 1
                cs = agent.controller.current
                pressed += any(cs.button.values()) or cs.main_stick != (0.5, 0.5) or cs.c_stick != (0.5, 0.5)
                if frames >= max_frames:
                    break
            agent.on_game_end(None)
            if frames >= max_frames:
                break
    finally:
        agent.close()
    stats = agent.game_stats
    tot = {k: sum(s[k] for s in stats) for k in ("frames", "answered", "late", "skipped", "exceptions")}
    tot.update(crashed=any(s["crashed"] for s in stats), policy_violations=max((s["policy_violations"] for s in stats), default=0),
               ms_p99=max((s["ms_p99"] or 0) for s in stats), ms_max=max((s["ms_max"] or 0) for s in stats),
               frames_with_input_pct=round(100 * pressed / max(1, frames), 1), wall_s=round(time.time() - t0, 1),
               character=agent.character.name, log=str(agent.log_path))
    tot["ok"] = not tot["crashed"] and tot["exceptions"] == 0 and tot["late"] == 0 and tot["policy_violations"] == 0
    return tot


def _tail(path: Path, n: int = 25) -> str:
    try:
        return "\n".join(path.read_text(errors="replace").splitlines()[-n:])
    except OSError:
        return ""


def main() -> None:
    ap = argparse.ArgumentParser(prog="practice")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("play", help="play real games in fast (headless, unthrottled) mode")
    p.add_argument("--bot", default="bot.py")
    p.add_argument("--opponent", default="cpu:7", help="one of: " + ", ".join(PRACTICE_SPECS))
    p.add_argument("--games", type=int, default=2)
    p.add_argument("--stage", default="fd", choices=sorted(STAGES))
    p.add_argument("--opp-char", default="FOX", help="opponent character (CPUs only; bots pick their own)")
    p.add_argument("--iso")
    p.add_argument("--sim", action="store_true",
                   help="play in the simulator (Melee's game code, no emulator): faster, no CPUs, no replay files")
    p.add_argument("--out", help="output dir (default runs/<timestamp>)")
    p.add_argument("--json", action="store_true", help="print the full report JSON instead of the compact view")
    c = sub.add_parser("check", help="offline: run the bot over recorded replays, report crashes and frame times")
    c.add_argument("--bot", default="bot.py")
    c.add_argument("--replay", action="append", help="replay(s) to use (default: replays/*.slp)")
    c.add_argument("--max-frames", type=int, default=20000)
    for q in (p, c):
        q.add_argument("--budget-ms", type=float, default=16.0, help="per-frame budget (evaluation uses 16)")
    a = ap.parse_args()
    bot = Path(a.bot).resolve()
    if a.cmd == "check":
        reps = [Path(r) for r in a.replay] if a.replay else sorted(Path("replays").glob("*.slp")) or sorted(REPLAYS.glob("*.slp"))
        if not reps:
            raise SystemExit("no replays found; pass --replay")
        r = check(bot, reps, a.budget_ms, a.max_frames)
        print(json.dumps(r, indent=1))
        if not r["ok"]:
            print("--- bot log tail ---\n" + _tail(Path(r["log"])))
        return
    if a.sim and not world.available():
        raise SystemExit("the simulator is not available on this machine; practice without --sim")
    iso = None if a.sim else find_iso(a.iso)
    out = Path(a.out or Path("runs") / time.strftime("%Y%m%d-%H%M%S")).resolve()
    rep = run_practice(bot, a.opponent, a.games, STAGES[a.stage], iso, out, melee.Character[a.opp_char.upper()], a.budget_ms,
                       "sim" if a.sim else "fast")
    if a.json:
        print(json.dumps(rep, indent=1, default=float))
        return
    for i, g in enumerate(rep["games"], 1):
        print(f"[game {i}] " + (compact(g["summary"], g["bot_port"]) if "summary" in g else f"{g['result']} stocks {g['stocks']}"))
        fs = g.get("bot_frame_stats") or {}
        print(f"  frames late {fs.get('late')} skipped {fs.get('skipped')} exceptions {fs.get('exceptions')} "
              f"p99 {fs.get('ms_p99')} ms crashed {fs.get('crashed')}" + (f"  replay {g['replay']}" if g.get("replay") else ""))
    print(json.dumps({"opponent": rep["opponent"], "stage": rep["stage"], **rep["record"],
                      "stock_diff_avg": rep["stock_diff_avg"], "report": str(out / "report.json"), "bot_logs": str(out / "bot-port*.log")}))
    for p in sorted({g["bot_port"] for g in rep["games"] if (g.get("bot_frame_stats") or {}).get("exceptions")}):
        print(f"--- bot log tail (port {p}) ---\n" + _tail(out / f"bot-port{p}.log"))


if __name__ == "__main__":
    main()
