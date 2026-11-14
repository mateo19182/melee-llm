"""CLI: uv run python -m melee_llm.netplay {host,start,stop,status,check,smoke,screenshot,view}. See docs/netplay.md."""
import argparse
import json
import signal
import sys
import threading
from dataclasses import asdict, fields

from melee_llm.netplay import control
from melee_llm.netplay.host import HostConfig, check, host, smoke


def _config_args(p: argparse.ArgumentParser, smoke_only: bool = False) -> None:
    for f in fields(HostConfig):
        flag = f"--{f.name.replace('_', '-')}"
        if f.name == "connect_code":
            p.add_argument(flag, required=True, help="the human's Slippi code, e.g. ABCD#123")
        elif f.name == "opponent":
            p.add_argument(flag, required=not smoke_only, default="idle",
                           help="match.py player spec: hal:MASTER, phillip:gm, mimic, faynt, reyn, coach:haiku, "
                                "llm_live:<model>, shine, idle")
        else:
            p.add_argument(flag, type=type(f.default), default=f.default)


def _config(a) -> HostConfig:
    return HostConfig(**{f.name: getattr(a, f.name) for f in fields(HostConfig)})


def main() -> None:
    p = argparse.ArgumentParser(prog="python -m melee_llm.netplay")
    sub = p.add_subparsers(dest="cmd", required=True)
    for name, help_ in [("host", "run a session in the foreground"), ("start", "run a session in the background"),
                        ("check", "preflight only")]:
        _config_args(sub.add_parser(name, help=help_))
    s = sub.add_parser("smoke", help="boot, navigate to Direct, type the code, screenshot; no human needed")
    _config_args(s, smoke_only=True)
    s.add_argument("--seconds", type=float, default=90)
    sub.add_parser("status")
    sub.add_parser("stop").add_argument("--force", action="store_true")
    sub.add_parser("screenshot").add_argument("path", nargs="?")
    sub.add_parser("view", help="noVNC view of :98 on the Tailscale IP")
    a = p.parse_args()

    if a.cmd == "host":
        stop = threading.Event()
        def on_term(*_):
            if stop.is_set():
                sys.exit(143)  # second signal: give up on finishing the game
            stop.set()
        signal.signal(signal.SIGTERM, on_term)
        signal.signal(signal.SIGINT, on_term)
        cfg = _config(a)

        def report(st):
            control.write_status(st)
            print(json.dumps({k: v for k, v in st.items() if k != "config"}, default=str), flush=True)

        for r in host(cfg, stop, report):
            print(json.dumps(asdict(r)))
    elif a.cmd == "start":
        print(json.dumps(control.start(**asdict(_config(a))), default=str))
    elif a.cmd == "check":
        problems = check(_config(a))
        print("\n".join(problems) or "ok")
        sys.exit(1 if problems else 0)
    elif a.cmd == "smoke":
        smoke(_config(a), a.seconds)
    elif a.cmd == "status":
        print(json.dumps(control.status(), indent=1, default=str))
    elif a.cmd == "stop":
        print(json.dumps(control.stop(a.force), default=str))
    elif a.cmd == "screenshot":
        print(control.screenshot(a.path))
    elif a.cmd == "view":
        print(control.view())


if __name__ == "__main__":
    main()
