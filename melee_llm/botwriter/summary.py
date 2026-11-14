"""Compact per-game summary of a .slp replay: the coding agent's main feedback signal.

CLI: python -m melee_llm.botwriter.summary GAME.slp [--port N] [--timeline]
"""
from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path

import melee

from melee_llm.runner import replay_states

DEAD = {a for a in melee.Action if a.name.startswith("DEAD_")} | {
    melee.Action.ON_HALO_DESCENT, melee.Action.ON_HALO_WAIT, melee.Action.ENTRY, melee.Action.ENTRY_START,
    melee.Action.ENTRY_END}
HURT = {a for a in melee.Action if a.name.startswith(("DAMAGE_", "TUMBLING"))}
KILL_WINDOW = 240  # frames: dying within 4 s of being hit counts as a kill, otherwise a self-destruct


def _blast_side(stage, x, y, action) -> str:
    named = {"DEAD_LEFT": "left", "DEAD_RIGHT": "right", "DEAD_DOWN": "bottom", "DEAD_UP": "top"}
    if action is not None and action.name in named:
        return named[action.name]
    left, right, top, bottom = melee.stages.BLASTZONES.get(stage, (-224, 224, 200, -108))
    d = {"left": abs(x - left), "right": abs(right - x), "top": abs(top - y), "bottom": abs(y - bottom)}
    if action is not None and action.name.startswith("DEAD_FLY"):
        return "top"
    return min(d, key=d.get)


class GameSummary:
    """Built frame by frame, from a replay or from a live game's GameStates."""

    def __init__(self):
        self.ports, self.stage, self.last, self.n = None, None, None, 0
        self.per: dict[int, dict] = {}
        self.prev: dict[int, tuple] = {}
        self.last_hit: dict[int, int] = {}
        self.last_alive: dict[int, tuple] = {}
        self.events = []

    def add(self, gs: melee.GameState) -> None:
        per, prev, last_hit, last_alive = self.per, self.prev, self.last_hit, self.last_alive
        if self.ports is None:
            self.ports, self.stage = sorted(int(p) for p in gs.players), gs.stage
            for p in self.ports:
                per[p] = {"character": gs.players[p].character.name, "stocks_lost": 0, "damage_taken": 0.0,
                          "hits_taken": 0, "deaths": [], "offstage_frames": 0, "alive_frames": 0,
                          "actions": Counter(), "_last_action": None}
        self.n += 1
        self.last = gs
        for p in self.ports:
            s = gs.players[p]
            d = per[p]
            stock, pct, action = int(s.stock), float(s.percent), s.action
            if action in HURT or s.hitstun_frames_left > 0:
                last_hit[p] = gs.frame
            if action not in DEAD:
                d["alive_frames"] += 1
                d["offstage_frames"] += bool(s.off_stage)
                last_alive[p] = (float(s.position.x), float(s.position.y), pct)
            if action != d["_last_action"]:
                d["actions"][action.name] += 1
                d["_last_action"] = action
            if p in prev:
                pstock, ppct, paction = prev[p]
                if stock < pstock:
                    x, y, at = last_alive.get(p, (0.0, 0.0, ppct))
                    side = _blast_side(self.stage, x, y, paction if paction in DEAD else action)
                    cause = "killed" if gs.frame - last_hit.get(p, -10**9) < KILL_WINDOW else "self-destruct"
                    death = {"frame": int(gs.frame), "percent": round(at, 1), "blast_zone": side, "cause": cause}
                    d["deaths"].append(death)
                    d["stocks_lost"] += 1
                    self.events.append({"port": p, **death})
                elif pct > ppct + 1e-3:
                    d["damage_taken"] += pct - ppct
                    d["hits_taken"] += 1
            prev[p] = (stock, pct, action)

    def result(self, replay: str | None = None, timeline: bool = False) -> dict:
        ports, per, last, n = self.ports, self.per, self.last, self.n
        if last is None:
            raise ValueError(f"{replay}: no in-game frames")
        out = {"replay": replay, "stage": self.stage.name, "frames": n, "seconds": round(n / 60, 1), "players": {}}
        for p in ports:
            d, s = per[p], last.players[p]
            opp = next((q for q in ports if q != p), p)
            out["players"][p] = {
                "character": d["character"], "final_stocks": int(s.stock), "final_percent": round(float(s.percent), 1),
                "stocks_lost": d["stocks_lost"], "damage_taken": round(d["damage_taken"], 1),
                "damage_dealt": round(per[opp]["damage_taken"], 1), "hits_landed": per[opp]["hits_taken"],
                "deaths": d["deaths"],
                "pct_time_offstage": round(100 * d["offstage_frames"] / max(1, d["alive_frames"]), 1),
                "top_actions": dict(d["actions"].most_common(15)),
            }
        ranked = sorted(ports, key=lambda p: (int(last.players[p].stock), -float(last.players[p].percent)), reverse=True)
        a, b = (last.players[ranked[0]], last.players[ranked[1]]) if len(ranked) > 1 else (None, None)
        out["winner"] = ranked[0] if a is not None and (int(a.stock), -float(a.percent)) != (int(b.stock), -float(b.percent)) else None
        if timeline:
            out["deaths_timeline"] = self.events
        return out


def summarize(slp: str | Path, timeline: bool = False) -> dict:
    g = GameSummary()
    for gs in replay_states(slp):
        g.add(gs)
    return g.result(str(slp), timeline)


def compact(summary: dict, port: int) -> str:
    """One readable block per game from the bot's point of view."""
    me = summary["players"][port]
    opp_port = next(p for p in summary["players"] if p != port)
    opp = summary["players"][opp_port]
    res = "WIN" if summary["winner"] == port else "DRAW" if summary["winner"] is None else "LOSS"
    deaths = ", ".join(f"{d['cause']}@{d['percent']}%({d['blast_zone']})" for d in me["deaths"]) or "none"
    kills = ", ".join(f"{d['cause']}@{d['percent']}%({d['blast_zone']})" for d in opp["deaths"]) or "none"
    acts = " ".join(f"{k}:{v}" for k, v in list(me["top_actions"].items())[:10])
    return (f"{res} {summary['stage']} {summary['seconds']}s | stocks {me['final_stocks']}-{opp['final_stocks']} | "
            f"dmg dealt {me['damage_dealt']} taken {me['damage_taken']} | hits {me['hits_landed']}-{opp['hits_landed']} | "
            f"offstage {me['pct_time_offstage']}%\n  my deaths: {deaths}\n  opp deaths: {kills}\n  my actions: {acts}")


def main() -> None:
    ap = argparse.ArgumentParser(prog="inspect-replay", description="Summarize a Slippi replay.")
    ap.add_argument("slp")
    ap.add_argument("--port", type=int, help="print the compact view from this port's side")
    ap.add_argument("--timeline", action="store_true", help="include every death with its frame")
    a = ap.parse_args()
    s = summarize(a.slp, a.timeline)
    print(compact(s, a.port) if a.port else json.dumps(s, indent=1))


if __name__ == "__main__":
    main()
