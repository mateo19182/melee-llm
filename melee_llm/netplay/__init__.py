"""Play our bots and LLM players against a human over Slippi Online Direct Connect. See docs/netplay.md."""
from melee_llm.netplay.control import screenshot, start, status, stop, view
from melee_llm.netplay.host import HostConfig, NetplayResult, check, host

__all__ = ["HostConfig", "NetplayResult", "check", "host", "screenshot", "start", "status", "stop", "view"]
