"""TypeSafe Jev client: POST /v1/systemone (structured state + typed questions → typed answers with probabilities).

The key is read from $TYPESAFE_API_KEY or ~/.secrets/typesafe.env and is never logged. Errors come back as a
failed `JevReply` (like `llm.Reply`), never raised, so a game thread can't die on a network hiccup.
See docs/jev.md.
"""
from __future__ import annotations

import os
import random
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path

import httpx

BASE_URL = "https://api.typesafe.ai"
SECRETS = Path.home() / ".secrets/typesafe.env"
USD_PER_MTOK = 0.042  # input tokens; output tokens are free (Jev 1.13/1.14 list price)
RETRY_STATUS = {408, 409, 429, 500, 502, 503, 504, 529}
MAX_CHOICES = 255


def api_key() -> str:
    if os.environ.get("TYPESAFE_API_KEY"):
        return os.environ["TYPESAFE_API_KEY"]
    if SECRETS.exists():
        for line in SECRETS.read_text().splitlines():
            k, _, v = line.partition("=")
            if k.strip().removeprefix("export ").strip() == "TYPESAFE_API_KEY":
                return v.strip().strip("'\"")
    raise RuntimeError(f"TYPESAFE_API_KEY not set and not in {SECRETS}")


def choice(criteria: dict[str, str], instructions: str) -> dict:
    if not 1 <= len(criteria) <= MAX_CHOICES:
        raise ValueError(f"a Jev choice takes 1-{MAX_CHOICES} options, got {len(criteria)}")
    return {"type": "choice", "instructions": instructions, "criteria": criteria}


def noul(instructions: str) -> dict:
    return {"type": "noul", "instructions": instructions}


@dataclass
class JevReply:
    answers: dict = field(default_factory=dict)  # question name → answer dict as returned
    model: str = ""
    latency_s: float = 0.0
    input_tokens: int = 0
    output_tokens: int = 0
    attempts: int = 0
    error: str = ""

    @property
    def ok(self) -> bool:
        return not self.error

    @property
    def usd(self) -> float:
        return self.input_tokens * USD_PER_MTOK / 1e6

    def pick(self, name: str) -> str | None:
        a = self.answers.get(name) or {}
        return a.get("choice")

    def top(self, name: str, k: int = 5) -> list[tuple[str, float]]:
        probs = (self.answers.get(name) or {}).get("probabilities") or {}
        return sorted(((o, round(float(p), 4)) for o, p in probs.items()), key=lambda t: -t[1])[:k]

    def confidence(self, name: str) -> float | None:
        return (self.answers.get(name) or {}).get("confidence")


class Jev:
    """Thread-safe; one keep-alive HTTP/1.1 connection pool. `deadline` bounds the whole call incl. retries,
    so a live player never waits on backoff for an answer that would be stale anyway."""

    def __init__(self, model: str = "jev-latest", timeout: float = 3.0, retries: int = 2, deadline: float | None = None,
                 base_url: str | None = None):
        self.model, self.timeout, self.retries = model, timeout, retries
        self.deadline = deadline if deadline is not None else timeout * (retries + 1)
        self.http = httpx.Client(base_url=base_url or os.environ.get("TYPESAFE_BASE_URL", BASE_URL),
                                 headers={"Authorization": f"Bearer {api_key()}"}, timeout=timeout)
        self._lock = threading.Lock()
        self.calls = self.errors = self.input_tokens = self.output_tokens = 0
        self.latencies: list[float] = []

    def ask(self, state, questions: dict[str, dict]) -> JevReply:
        body = {"model": self.model, "state": state, "questions": questions}
        t0 = time.perf_counter()
        rep, err = JevReply(model=self.model), ""
        for attempt in range(self.retries + 1):
            rep.attempts = attempt + 1
            left = self.deadline - (time.perf_counter() - t0)
            if left <= 0:
                break
            wait = None
            try:
                r = self.http.post("/v1/systemone", json=body, timeout=min(self.timeout, left))
                if r.status_code == 200:
                    j = r.json()
                    u = j.get("usage") or {}
                    rep.answers, rep.model = j.get("answers") or {}, j.get("model", self.model)
                    rep.input_tokens, rep.output_tokens = int(u.get("input_tokens", 0)), int(u.get("output_tokens", 0))
                    err = ""
                    break
                err = f"HTTP {r.status_code}: {r.text[:200]}"
                if r.status_code not in RETRY_STATUS:
                    break
                ra = r.headers.get("retry-after")
                wait = float(ra) if ra and ra.replace(".", "", 1).isdigit() else None
            except (httpx.TimeoutException, httpx.TransportError) as e:
                err = f"{type(e).__name__}: {str(e)[:160]}"
            except ValueError as e:  # bad JSON
                err = f"bad response: {str(e)[:160]}"
                break
            backoff = wait if wait is not None else min(2.0, 0.1 * 2 ** attempt) * (0.5 + random.random())
            if attempt < self.retries and backoff < self.deadline - (time.perf_counter() - t0):
                time.sleep(backoff)
        rep.latency_s, rep.error = time.perf_counter() - t0, err
        with self._lock:
            self.calls += 1
            self.errors += bool(err)
            self.input_tokens += rep.input_tokens
            self.output_tokens += rep.output_tokens
            self.latencies.append(rep.latency_s)
        return rep

    def stats(self) -> dict:
        with self._lock:
            lat = sorted(self.latencies)
        q = (lambda p: round(lat[min(len(lat) - 1, int(p * len(lat)))], 3)) if lat else (lambda p: None)
        return {"calls": self.calls, "errors": self.errors, "input_tokens": self.input_tokens,
                "output_tokens": self.output_tokens, "usd": round(self.input_tokens * USD_PER_MTOK / 1e6, 6),
                "latency_p50_s": q(.5), "latency_p90_s": q(.9), "latency_max_s": lat[-1] if lat else None}

    def close(self) -> None:
        self.http.close()
