"""Web UI: live view with the LLM panel, job queue for the live slot and headless pool, result dashboards.

Server: `python -m melee_llm.web.server` (systemd user unit melee-web, 127.0.0.1:8770).
Live slot owner: `python -m melee_llm.web.worker` (unit melee-arena); the arena is its idle filler.
"""
