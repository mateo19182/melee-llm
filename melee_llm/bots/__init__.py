"""Learned Melee bots as Agents. Each runs in a subprocess under its own venv in vendor/; see docs/bots.md.

The match.py spec argument (`hal:MASTER`, `phillip:gm`, `mimic:fox-master`, `faynt:10M-Arena`, `reyn:<phrase>`) picks
the bot's style/model. After setup, `agent.steer` holds every knob with its effective value; a coach
can change it mid-game (see docs/bots.md for when each knob takes effect).
"""
from __future__ import annotations

from melee_llm.bots.agent import VENDOR, BotAgent


class HAL(BotAgent):
    """ericyuegu/hal 250M. arg: imitated identity (connect code in the vocab, or PLATINUM/DIAMOND/MASTER).

    steer: identity (next game), return_target ('p90', float in [-20, 140] or None), temperature [0.8, 1.1].
    """
    bot, python, cwd = "hal", VENDOR / "hal/.venv/bin/python", VENDOR / "hal"

    def __init__(self, arg=None, **kw):
        super().__init__(arg, **kw)
        if arg:
            self.steer["identity"] = arg


class Phillip(BotAgent):
    """vladfi1/slippi-ai ONNX exports. arg: model name in vendor/slippi-ai/models (default: gm).

    steer: name (nametag from the model's name_map), rating (float), temperature.
    """
    bot, python, cwd = "phillip", VENDOR / "slippi-ai/.venv/bin/python", VENDOR / "slippi-ai"

    def init_config(self):
        return {"model": self.arg or "gm", **self.config}


class MIMIC(BotAgent):
    """erickfm/MIMIC per-character BC transformers. arg: checkpoint dir (default: from the character).

    steer: temperature, top_k, top_p.
    """
    bot, python, cwd = "mimic", VENDOR / "MIMIC/.venv/bin/python", VENDOR / "MIMIC"

    def init_config(self):
        return {"model": self.arg, **self.config}


class Faynt(BotAgent):
    """frisson-labs Faynt, one checkpoint for 26 characters. arg: variant (default: 10M-Arena).

    steer: temperature.
    """
    bot, python, cwd = "faynt", VENDOR / "Faynt-Tournament/.venv/bin/python", VENDOR / "Faynt-Tournament"

    def init_config(self):
        return {"model": self.arg or "10M-Arena", **self.config}


class ReynBot(BotAgent):
    """frisson-labs Reyn-26C, language-steerable, 26 characters. arg: initial command phrase (default: none).

    steer: command (phrase, or None to clear; the router may abstain and keep the old one), temperature.
    applied_steer adds `active` (the held command row) and `reply` (the router's last answer).
    """
    bot, python, cwd = "reyn", VENDOR / "Reyn/.venv/bin/python", VENDOR / "Reyn"

    def __init__(self, arg=None, **kw):
        super().__init__(arg, **kw)
        if arg:
            self.steer["command"] = arg


BOTS = {"hal": HAL, "phillip": Phillip, "mimic": MIMIC, "faynt": Faynt, "reyn": ReynBot}
