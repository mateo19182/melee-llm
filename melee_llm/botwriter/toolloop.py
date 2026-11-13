"""Minimal coding-agent loop over any OpenAI-compatible /chat/completions endpoint.

Tools: bash (cwd = sandbox), read_file, write_file, edit_file. The loop runs until the wall-clock
deadline, the token budget or the turn limit; if the model stops calling tools it is told how much
time is left and asked to continue (like StarSkirmish, there is no submit tool).
"""
from __future__ import annotations

import json
import os
import signal
import subprocess
import time
import urllib.error
import urllib.request
from pathlib import Path

TOOLS = [
    {"type": "function", "function": {"name": "bash", "description": "Run a shell command in the sandbox directory. Output is truncated to 12k characters.",
     "parameters": {"type": "object", "properties": {"command": {"type": "string"}, "timeout_s": {"type": "integer", "description": "default 900"}}, "required": ["command"]}}},
    {"type": "function", "function": {"name": "read_file", "description": "Read a text file (path relative to the sandbox).",
     "parameters": {"type": "object", "properties": {"path": {"type": "string"}, "offset": {"type": "integer"}, "limit": {"type": "integer"}}, "required": ["path"]}}},
    {"type": "function", "function": {"name": "write_file", "description": "Create or overwrite a file in the sandbox.",
     "parameters": {"type": "object", "properties": {"path": {"type": "string"}, "content": {"type": "string"}}, "required": ["path", "content"]}}},
    {"type": "function", "function": {"name": "edit_file", "description": "Replace one exact, unique occurrence of old with new in a file.",
     "parameters": {"type": "object", "properties": {"path": {"type": "string"}, "old": {"type": "string"}, "new": {"type": "string"}}, "required": ["path", "old", "new"]}}},
]
MAX_OUT = 12_000
KEEP_RECENT_TOOL_RESULTS = 12  # older tool outputs are elided to bound the context


class Sandbox:
    def __init__(self, root: Path, env: dict):
        self.root, self.env = root.resolve(), env

    def _path(self, p: str) -> Path:
        q = (self.root / p).resolve()
        if q != self.root and self.root not in q.parents:
            raise PermissionError(f"{p} is outside the sandbox")
        return q

    def call(self, name: str, args: dict, deadline: float) -> str:
        try:
            if name == "bash":
                timeout = max(1, min(int(args.get("timeout_s") or 900), int(deadline - time.time())))
                p = subprocess.Popen(["bash", "-lc", args["command"]], cwd=self.root, env=self.env, text=True,
                                     stdout=subprocess.PIPE, stderr=subprocess.STDOUT, start_new_session=True)
                try:
                    out, _ = p.communicate(timeout=timeout)
                except subprocess.TimeoutExpired:
                    os.killpg(p.pid, signal.SIGKILL)
                    out = (p.communicate()[0] or "") + f"\n[killed after {timeout}s]"
                out = f"[exit {p.returncode}]\n{out}"
            elif name == "read_file":
                lines = self._path(args["path"]).read_text(errors="replace").splitlines()
                off, lim = int(args.get("offset") or 0), int(args.get("limit") or 2000)
                out = "\n".join(f"{i + 1}\t{line}" for i, line in enumerate(lines[off:off + lim], off))
            elif name == "write_file":
                p = self._path(args["path"])
                p.parent.mkdir(parents=True, exist_ok=True)
                p.write_text(args["content"])
                out = f"wrote {len(args['content'])} chars to {args['path']}"
            elif name == "edit_file":
                p = self._path(args["path"])
                s = p.read_text()
                if s.count(args["old"]) != 1:
                    return f"error: old text found {s.count(args['old'])} times, need exactly 1"
                p.write_text(s.replace(args["old"], args["new"]))
                out = "edited"
            else:
                out = f"error: unknown tool {name}"
        except Exception as e:
            out = f"error: {type(e).__name__}: {e}"
        return out if len(out) <= MAX_OUT else out[:MAX_OUT // 2] + "\n[... truncated ...]\n" + out[-MAX_OUT // 2:]


def _post(base_url: str, key: str, body: dict, timeout: float) -> dict:
    req = urllib.request.Request(base_url.rstrip("/") + "/chat/completions", data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json", "Authorization": f"Bearer {key}"})
    for attempt in range(5):
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return json.loads(r.read())
        except urllib.error.HTTPError as e:
            if e.code < 500 and e.code != 429:
                raise RuntimeError(f"HTTP {e.code}: {e.read()[:500]!r}") from None
        except (urllib.error.URLError, TimeoutError):
            pass
        time.sleep(2 ** attempt)
    raise RuntimeError("API unreachable after 5 attempts")


def run(sandbox: Path, prompt: str, model: str, base_url: str, api_key: str, deadline: float, transcript: Path,
        env: dict, max_tokens_total: int = 5_000_000, max_turns: int = 1000, system: str | None = None) -> dict:
    box = Sandbox(sandbox, env)
    messages = [{"role": "system", "content": system or "You are an expert programmer working autonomously in a sandbox."},
                {"role": "user", "content": prompt}]
    usage = {"prompt_tokens": 0, "completion_tokens": 0, "turns": 0}
    idle, stop = 0, "deadline"
    with open(transcript, "a") as log:
        log.write(json.dumps({"t": time.time(), "messages": messages}) + "\n")
        while time.time() < deadline:
            if usage["turns"] >= max_turns:
                stop = "max_turns"
                break
            if usage["prompt_tokens"] + usage["completion_tokens"] >= max_tokens_total:
                stop = "token_budget"
                break
            try:
                resp = _post(base_url, api_key, {"model": model, "messages": messages, "tools": TOOLS},
                             timeout=max(30, min(600, deadline - time.time())))
            except RuntimeError as e:
                log.write(json.dumps({"t": time.time(), "error": str(e)}) + "\n")
                stop = "api_error"
                break
            usage["turns"] += 1
            for k in ("prompt_tokens", "completion_tokens"):
                usage[k] += int((resp.get("usage") or {}).get(k) or 0)
            msg = resp["choices"][0]["message"]
            msg = {k: v for k, v in msg.items() if k in ("role", "content", "tool_calls") and v is not None}
            msg.setdefault("content", "")
            messages.append(msg)
            log.write(json.dumps({"t": time.time(), "assistant": msg, "usage": resp.get("usage")}) + "\n")
            calls = msg.get("tool_calls") or []
            if not calls:
                idle += 1
                if idle >= 3:
                    stop = "model_stopped"
                    break
                left = int((deadline - time.time()) / 60)
                messages.append({"role": "user", "content": f"{left} minutes left. Keep improving bot.py until the time is up."})
                continue
            idle = 0
            for c in calls:
                try:
                    args = json.loads(c["function"].get("arguments") or "{}")
                except ValueError:
                    args = {}
                out = box.call(c["function"]["name"], args, deadline)
                messages.append({"role": "tool", "tool_call_id": c["id"], "content": out})
                log.write(json.dumps({"t": time.time(), "tool": c["function"]["name"], "args": args, "result": out}) + "\n")
            tool_idx = [i for i, m in enumerate(messages) if m["role"] == "tool"]
            for i in tool_idx[:-KEEP_RECENT_TOOL_RESULTS]:
                if len(messages[i]["content"]) > 300:
                    messages[i]["content"] = messages[i]["content"][:300] + "\n[older output elided]"
    usage["stop"] = stop
    return usage
