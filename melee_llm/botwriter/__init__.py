"""Bot-writer track: coding agents write single-file Melee bots that are then ranked on a ladder.

host.py runs a submitted bot in a child process; agent.py wraps it as an Agent with a per-frame
time budget; practice.py and summary.py are the sandbox tools; ladder.py ranks bots; session.py
launches a coding agent on a fresh sandbox. See docs/bot-writer.md.
"""
