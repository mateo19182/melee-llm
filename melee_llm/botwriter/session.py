"""Launch a coding agent on a fresh sandbox with a budget; collect its bot, transcript and cost.

  python -m melee_llm.botwriter.session sandbox --dest DIR [--iso ISO]      # just build a sandbox
  python -m melee_llm.botwriter.session run --harness claude --model sonnet --minutes 60 --budget-usd 20 --name sonnet/run1
  python -m melee_llm.botwriter.session run --harness openai --model claude-haiku-4-5-20251001 --minutes 5 --name haiku/smoke

Harnesses: claude (Claude Code `claude -p`), codex (`codex exec`), openai (toolloop.py over an
OpenAI-compatible endpoint; default the local CLIProxy, key CLIPROXY_API_KEY from env or
~/.hermes/.env). Output: $BOTWRITER_HOME/sessions/<id>/{meta.json, transcript.jsonl, final/bot.py}.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import secrets
import shutil
import signal
import subprocess
import sys
import time
import uuid
from pathlib import Path

from melee_llm.botwriter import toolloop

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
HOME = Path(os.environ.get("BOTWRITER_HOME", Path.home() / ".local/share/melee-llm/botwriter"))
SAMPLE_REPLAYS = ["sample-slippi-js-itemExport.slp", "sample-slippi-js-actionEdgeCases.slp"]
PROMPT = """You are in a sandbox directory for writing a Super Smash Bros. Melee bot. Read README.md first.
You have {minutes} minutes of wall-clock time (run tools/time-left to check). The session is stopped
at the deadline, and whatever is in bot.py then is your entry. Nobody will answer questions: work
autonomously, keep bot.py loading at all times (tools/check-bot), and keep improving it until the
time is up.{no_iso}"""
NO_ISO = ("\n\nNOTE: no Melee ISO is configured in this session, so tools/practice cannot play games. "
          "Use tools/check-bot, the docs and the frame data.")


def _script(path: Path, body: str) -> None:
    path.write_text("#!/usr/bin/env bash\nset -e\ncd \"$(dirname \"$0\")/..\"\n" + body + "\n")
    path.chmod(0o755)


def make_sandbox(dest: Path, iso: str | None, deadline: float | None, session_id: str = "manual") -> Path:
    """Copy the template plus scripted opponents and sample replays; write tool wrappers."""
    if dest.exists():
        raise SystemExit(f"{dest} already exists")
    shutil.copytree(HERE / "template", dest, ignore=shutil.ignore_patterns("__pycache__"))
    shutil.copytree(HERE / "baselines", dest / "opponents", ignore=shutil.ignore_patterns("__pycache__"))
    for d in ("old", "runs", "replays"):
        (dest / d).mkdir(exist_ok=True)
    for name in SAMPLE_REPLAYS:
        if (ROOT / "replays" / name).exists():
            shutil.copy(ROOT / "replays" / name, dest / "replays" / name)
    env = f'export PYTHONPATH="{ROOT}" BOTWRITER_SESSION="{session_id}"' + (f' MELEE_ISO="{iso}"' if iso else "")
    py = sys.executable
    tools = dest / "tools"
    tools.mkdir(exist_ok=True)
    _script(tools / "practice", f'{env}\nexec "{py}" -m melee_llm.botwriter.practice play "$@"')
    _script(tools / "check-bot", f'{env}\nexec "{py}" -m melee_llm.botwriter.practice check "$@"')
    _script(tools / "inspect-replay", f'{env}\nexec "{py}" -m melee_llm.botwriter.summary "$@"')
    dl = f"{deadline:.0f}" if deadline else ""
    _script(tools / "time-left", f'python3 -c "import time; d=\'{dl}\'; print(\'no deadline\' if not d else '
                                 f'f\'{{max(0,(float(d)-time.time()))/60:.1f}} minutes left\')"')
    return dest


def _api_key() -> str:
    key = os.environ.get("CLIPROXY_API_KEY")
    if not key:
        env = Path.home() / ".hermes/.env"
        for line in env.read_text().splitlines() if env.exists() else []:
            if line.startswith("CLIPROXY_API_KEY="):
                key = line.split("=", 1)[1].strip().strip("'\"")
    if not key:
        raise SystemExit("CLIPROXY_API_KEY not found")
    return key


def _agent_env(sandbox: Path, session_id: str) -> dict:
    """Child env without our secrets. The marker lets us find stray Dolphins afterwards."""
    drop = ("CLIPROXY_API_KEY", "OPENAI_API_KEY", "GITHUB_TOKEN", "GH_TOKEN", "HF_TOKEN")
    env = {k: v for k, v in os.environ.items() if k not in drop and not k.startswith("BOTWRITER_")}
    env["BOTWRITER_SESSION"] = session_id
    env["PATH"] = f"{sandbox / 'tools'}:{env.get('PATH', '/usr/bin:/bin')}"
    return env


def _kill_marked(session_id: str) -> int:
    """Kill leftover processes (e.g. Dolphins from a practice run cut off at the deadline)."""
    n, me = 0, os.getpid()
    for pid in filter(str.isdigit, os.listdir("/proc")):
        if int(pid) == me:
            continue
        try:
            env = Path(f"/proc/{pid}/environ").read_bytes()
        except OSError:
            continue
        if f"BOTWRITER_SESSION={session_id}".encode() in env.split(b"\0"):
            try:
                os.kill(int(pid), signal.SIGKILL)
                n += 1
            except OSError:
                pass
    return n


CONTINUE = "{left:.0f} minutes are left. Keep improving bot.py (practice, inspect, iterate) until the time is up."
MAX_CONTINUATIONS = 30


def _cli_cmd(harness: str, model: str, prompt: str, sandbox: Path, budget_usd: float | None, effort: str | None,
             claude_session: str | None = None, resume: bool = False) -> list[str]:
    if harness == "claude":
        cmd = ["claude", "-p", prompt, "--model", model, "--output-format", "stream-json", "--verbose",
               "--permission-mode", "bypassPermissions", "--safe-mode", "--strict-mcp-config",
               "--disallowedTools", "WebFetch,WebSearch"]
        cmd += ["--resume", claude_session] if resume else ["--session-id", claude_session]
        if budget_usd:
            cmd += ["--max-budget-usd", str(budget_usd)]
        if effort:
            cmd += ["--effort", effort]
        return cmd
    if harness == "codex":
        cmd = ["codex", "exec", "--json", "-m", model, "-C", str(sandbox), "--skip-git-repo-check", "--ephemeral",
               "--ignore-user-config", "--dangerously-bypass-approvals-and-sandbox"]
        if effort:
            cmd += ["-c", f"model_reasoning_effort={effort}"]
        return cmd + [prompt]
    raise ValueError(harness)


def _cost_from_transcript(harness: str, path: Path) -> dict:
    out = {}
    for line in path.read_text(errors="replace").splitlines() if path.exists() else []:
        try:
            ev = json.loads(line)
        except ValueError:
            continue
        if harness == "claude" and ev.get("type") == "result":  # one per invocation; sum over continuations
            out["cost_usd"] = round(out.get("cost_usd", 0) + (ev.get("total_cost_usd") or 0), 6)
            out["num_turns"] = out.get("num_turns", 0) + (ev.get("num_turns") or 0)
            out["invocations"] = out.get("invocations", 0) + 1
            u = out.setdefault("usage", {})
            for k, v in (ev.get("usage") or {}).items():
                if isinstance(v, (int, float)):
                    u[k] = u.get(k, 0) + v
            out["result_subtype"] = ev.get("subtype")
        elif harness == "codex" and ev.get("type") in ("turn.completed", "token_count"):
            out["usage"] = ev.get("usage") or ev.get("info") or out.get("usage")
    return out


def _invoke(cmd: list[str], cwd: Path, env: dict, transcript: Path, stderr: Path, deadline: float) -> str:
    with open(transcript, "ab") as out, open(stderr, "ab") as err:
        p = subprocess.Popen(cmd, cwd=cwd, env=env, stdin=subprocess.DEVNULL, stdout=out, stderr=err, start_new_session=True)
        try:
            return f"code {p.wait(timeout=max(1, deadline - time.time()))}"
        except subprocess.TimeoutExpired:
            os.killpg(p.pid, signal.SIGTERM)
            try:
                p.wait(timeout=20)
            except subprocess.TimeoutExpired:
                os.killpg(p.pid, signal.SIGKILL)
                p.wait()
            return "deadline"


def run_session(harness: str, model: str, minutes: float, name: str, iso: str | None, budget_usd: float | None,
                effort: str | None, base_url: str, max_tokens: int) -> dict:
    sid = time.strftime("%Y%m%d-%H%M%S") + "-" + secrets.token_hex(3)
    sdir = HOME / "sessions" / sid
    sandbox = HOME / "sandboxes" / secrets.token_hex(8)  # not under the session record, unguessable sibling
    sdir.mkdir(parents=True)
    t0 = time.time()
    deadline = t0 + minutes * 60
    make_sandbox(sandbox, iso, deadline, sid)
    prompt = PROMPT.format(minutes=minutes, no_iso="" if iso else NO_ISO)
    env = _agent_env(sandbox, sid)
    meta = {"id": sid, "name": name, "harness": harness, "model": model, "effort": effort, "minutes": minutes,
            "budget_usd": budget_usd, "iso": bool(iso), "sandbox": str(sandbox), "started": t0, "prompt": prompt}
    (sdir / "meta.json").write_text(json.dumps(meta, indent=1))
    transcript = sdir / "transcript.jsonl"
    if harness == "openai":
        usage = toolloop.run(sandbox, prompt, model, base_url, _api_key(), deadline, transcript, env, max_tokens)
        meta.update(usage=usage, exit="loop:" + usage["stop"])
    else:
        claude_session = str(uuid.uuid4()) if harness == "claude" else None
        meta["claude_session"] = claude_session
        msg, resume = prompt, False
        for _ in range(MAX_CONTINUATIONS + 1):
            spent = _cost_from_transcript(harness, transcript).get("cost_usd") or 0
            left_usd = None if budget_usd is None else budget_usd - spent
            if left_usd is not None and left_usd <= 0.01:
                meta["exit"] = "budget"
                break
            meta["exit"] = _invoke(_cli_cmd(harness, model, msg, sandbox, left_usd, effort, claude_session, resume),
                                   sandbox, env, transcript, sdir / "stderr.log", deadline)
            left_min = (deadline - time.time()) / 60
            # the agent ended its turn early: nudge it to keep going (claude only; codex exec has no resume here)
            if meta["exit"] == "deadline" or harness != "claude" or left_min < 1:
                break
            msg, resume = CONTINUE.format(left=left_min), True
        meta.update(_cost_from_transcript(harness, transcript))
    meta["stray_processes_killed"] = _kill_marked(sid)
    meta["wall_s"] = round(time.time() - t0, 1)
    final = sdir / "final"
    final.mkdir()
    bot = sandbox / "bot.py"
    if bot.exists():
        shutil.copy(bot, final / "bot.py")
        meta["bot_sha256"] = hashlib.sha256(bot.read_bytes()).hexdigest()
        meta["bot_lines"] = len(bot.read_text(errors="replace").splitlines())
        meta["validation"] = validate(final / "bot.py", sandbox / "replays")
    shutil.make_archive(str(sdir / "sandbox"), "gztar", sandbox)  # keep practice logs/old versions for analysis
    (sdir / "meta.json").write_text(json.dumps(meta, indent=1, default=str))
    return meta


def validate(bot: Path, replay_dir: Path) -> dict:
    """Offline crash/time check of the final bot (the same as tools/check-bot)."""
    replays = sorted(replay_dir.glob("*.slp"))
    if not replays:
        return {"skipped": "no replays"}
    cmd = [sys.executable, "-m", "melee_llm.botwriter.practice", "check", "--bot", str(bot), "--max-frames", "6000"]
    for r in replays:
        cmd += ["--replay", str(r)]
    p = subprocess.run(cmd, capture_output=True, text=True, env={**os.environ, "PYTHONPATH": str(ROOT)}, timeout=600)
    try:
        return json.loads(p.stdout.split("--- bot log")[0])
    except ValueError:
        return {"ok": False, "error": (p.stdout + p.stderr)[-2000:]}


def main() -> None:
    ap = argparse.ArgumentParser(prog="session")
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("sandbox")
    s.add_argument("--dest", required=True)
    s.add_argument("--iso", default=os.environ.get("MELEE_ISO"))
    s.add_argument("--minutes", type=float)
    r = sub.add_parser("run")
    r.add_argument("--harness", choices=["claude", "codex", "openai"], required=True)
    r.add_argument("--model", required=True)
    r.add_argument("--minutes", type=float, default=60)
    r.add_argument("--name", help="leaderboard name, '<model>/<run>' (default: model/<session id>)")
    r.add_argument("--iso", default=os.environ.get("MELEE_ISO"))
    r.add_argument("--budget-usd", type=float, help="claude only: --max-budget-usd")
    r.add_argument("--effort", help="reasoning effort passed to the CLI")
    r.add_argument("--base-url", default="http://127.0.0.1:8317/v1", help="openai harness endpoint")
    r.add_argument("--max-tokens", type=int, default=5_000_000, help="openai harness total token budget")
    a = ap.parse_args()
    if a.cmd == "sandbox":
        dl = time.time() + a.minutes * 60 if a.minutes else None
        print(make_sandbox(Path(a.dest).resolve(), a.iso, dl))
        return
    meta = run_session(a.harness, a.model, a.minutes, a.name or f"{a.model}/{int(time.time())}", a.iso,
                       a.budget_usd, a.effort, a.base_url, a.max_tokens)
    print(json.dumps({k: meta.get(k) for k in ("id", "name", "exit", "wall_s", "cost_usd", "usage", "validation")}, indent=1, default=str))


if __name__ == "__main__":
    main()
