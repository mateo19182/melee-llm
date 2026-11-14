"""OpenAI-compatible chat client (local CLIProxy by default, any vLLM/llama.cpp server via base_url).

The API key is read from $MELEE_LLM_API_KEY, $CLIPROXY_API_KEY or ~/.hermes/.env and is never logged.
"""
from __future__ import annotations

import json
import os
import re
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path

import openai

DEFAULT_BASE_URL = "http://127.0.0.1:8317/v1"
HERMES_ENV = Path.home() / ".hermes/.env"


def api_key() -> str:
    for var in ("MELEE_LLM_API_KEY", "CLIPROXY_API_KEY"):
        if os.environ.get(var):
            return os.environ[var]
    if HERMES_ENV.exists():
        for line in HERMES_ENV.read_text().splitlines():
            k, _, v = line.partition("=")
            if k.strip().removeprefix("export ").strip() == "CLIPROXY_API_KEY":
                return v.strip().strip("'\"")
    return "none"  # local servers usually ignore the key


def list_models(base_url: str | None = None, timeout: float = 5.0) -> list[str]:
    """Model ids the server offers (CLIProxy /v1/models)."""
    client = openai.OpenAI(base_url=base_url or os.environ.get("MELEE_LLM_BASE_URL", DEFAULT_BASE_URL),
                           api_key=api_key(), timeout=timeout, max_retries=0)
    return sorted(m.id for m in client.models.list().data)


@dataclass
class Reply:
    args: dict | None  # parsed tool arguments / JSON object, None if unparseable
    text: str = ""
    model: str = ""
    latency_s: float = 0.0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    mode: str = ""  # "tool" | "json" | "error"
    error: str = ""
    extra: dict = field(default_factory=dict)

    def log(self) -> dict:
        return asdict(self)


def parse_json(text: str) -> dict | None:
    """First JSON object in text (tolerates ```json fences and prose around it)."""
    m = re.search(r"\{.*\}", text or "", re.S)
    if not m:
        return None
    try:
        v = json.loads(m.group(0))
        return v if isinstance(v, dict) else None
    except json.JSONDecodeError:
        return None


class LLM:
    def __init__(self, model: str, base_url: str | None = None, timeout: float = 20.0, mode: str = "tool",
                 max_tokens: int = 400, temperature: float | None = None, effort: str | None = "none"):
        """effort → `reasoning_effort`; "none" disables hidden thinking (fastest), None omits the field.
        Reasoning tokens count against max_tokens, so keep headroom above the ~60-token answer."""
        self.model, self.mode, self.max_tokens, self.temperature = model, mode, max_tokens, temperature
        self.effort = effort
        self.client = openai.OpenAI(base_url=base_url or os.environ.get("MELEE_LLM_BASE_URL", DEFAULT_BASE_URL),
                                    api_key=api_key(), timeout=timeout, max_retries=0)

    def choose(self, system: str, user: str, tool: dict, images: list[str] | None = None) -> Reply:
        """Ask for one call of `tool`. mode='tool' uses function calling, 'json' asks for a bare JSON object.
        `images` are data URIs (or URLs), sent before the text as OpenAI `image_url` parts."""
        content: str | list = user
        if images:
            content = [{"type": "image_url", "image_url": {"url": u}} for u in images] + [{"type": "text", "text": user}]
        msgs = [{"role": "system", "content": system}, {"role": "user", "content": content}]
        kw: dict = {"model": self.model, "max_tokens": self.max_tokens}
        if self.temperature is not None:
            kw["temperature"] = self.temperature
        if self.effort:
            kw["reasoning_effort"] = self.effort
        if self.mode == "tool":
            kw |= {"tools": [tool], "tool_choice": {"type": "function", "function": {"name": tool["function"]["name"]}}}
        else:
            schema = json.dumps(tool["function"]["parameters"], separators=(",", ":"))
            msgs[0]["content"] += f"\n\nReply with ONLY a JSON object matching this schema:\n{schema}"
        t0 = time.perf_counter()
        try:
            r = self.client.chat.completions.create(messages=msgs, **kw)
        except Exception as e:  # network/timeout/HTTP errors are logged as a failed decision
            return Reply(None, model=self.model, latency_s=time.perf_counter() - t0, mode="error",
                         error=f"{type(e).__name__}: {str(e)[:200]}")
        dt = time.perf_counter() - t0
        msg = r.choices[0].message if r.choices else None
        usage = r.usage
        rep = Reply(None, text=(msg.content or "") if msg else "", model=r.model or self.model, latency_s=dt,
                    prompt_tokens=getattr(usage, "prompt_tokens", 0) or 0,
                    completion_tokens=getattr(usage, "completion_tokens", 0) or 0)
        calls = (msg.tool_calls or []) if msg else []
        if calls:
            rep.mode, rep.args = "tool", parse_json(calls[0].function.arguments)
        else:
            rep.mode, rep.args = "json", parse_json(rep.text)
        if rep.args is None:
            rep.error = "unparseable reply"
        return rep
