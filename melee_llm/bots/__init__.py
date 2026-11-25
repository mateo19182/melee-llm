"""Learned Melee bots as Agents. Each runs in a subprocess under its own venv in vendor/; see docs/bots.md.

The spec argument (`hal:MASTER`, `phillip:gm`, `mimic:fox-master`, `faynt:10M-Arena`, `reyn:<phrase>`, `meleebot:bc-6m-v1`) picks
the bot's style/model. After setup, `agent.steer` holds every knob with its effective value; a coach
can change it mid-game (see docs/bots.md for when each knob takes effect).
"""
from __future__ import annotations

from melee_llm.bots.agent import VENDOR, BotAgent
from melee_llm.paths import DATA, ROOT


class HAL(BotAgent):
    """ericyuegu/hal 250M. arg: imitated identity (connect code in the vocab, or PLATINUM/DIAMOND/MASTER),
    optionally followed by initial steer values, `delay=N` (0-11 frames of input delay) and `run=NAME` (our own
    fine-tuned weights instead of the released ones), e.g. `AMSA#0,return_target=60,temperature=0.9,delay=3`.

    steer: identity (next game), return_target ('p90', float in [-20, 140] or None), temperature [0.8, 1.1].
    """
    bot, python, cwd = "hal", VENDOR / "hal/.venv/bin/python", VENDOR / "hal"

    def __init__(self, arg=None, **kw):
        identity, *opts = (arg or "").split(",")
        super().__init__(identity or None, **kw)
        if identity:
            self.steer["identity"] = identity
        for o in opts:
            k, _, v = o.partition("=")
            if k == "delay":  # fixed for the process, so it is config, not steer
                self.config["delay"] = int(v)
            elif k == "run":  # a fine-tune of ours: data/train/runs/<run>/last.hal (train/haltrain)
                self.config["weights"] = str(DATA / "train/runs" / v / "last.hal")
            else:
                self.steer[k] = None if v == "None" else v if v == "p90" else float(v)


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
    """frisson-labs Faynt, one checkpoint for 26 characters. arg: variant (default: 10M-Arena) or a checkpoint
    folder, optionally followed by bot config, e.g. `/abs/ckpt/step-N,own=1,name=18,items=4` for our own models
    (bot_faynt.py).

    steer: temperature.
    """
    bot, python, cwd = "faynt", VENDOR / "Faynt-Tournament/.venv/bin/python", VENDOR / "Faynt-Tournament"

    def init_config(self):
        model, *opts = (self.arg or "").split(",")
        return {"model": model or "10M-Arena", **{k: int(v) if v.isdigit() else v for k, _, v in (o.partition("=") for o in opts)},
                **self.config}


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


class MeleeBot(BotAgent):
    """Our own behaviour-cloned bot (train/meleebot). arg: run name in data/train/runs (default: bc-6m-v1),
    optionally followed by initial steer values, e.g. `bc-20m-ft,delay=3,rank=PRO`.

    steer: delay (0-12 frames of reaction delay), rank (UNKNOWN/PLATINUM/DIAMOND/MASTER/PRO), win (1, 0 or None),
    temperature.
    """
    bot, python, cwd = "meleebot", ROOT / "train/.venv/bin/python", ROOT / "train"

    def __init__(self, arg=None, **kw):
        run, *opts = (arg or "").split(",")
        super().__init__(run or None, **kw)
        for o in opts:
            k, _, v = o.partition("=")
            self.steer[k] = v if k == "rank" else None if v == "None" else float(v) if k == "temperature" else int(v)

    def init_config(self):
        return {"checkpoint": str(DATA / "train/runs" / (self.arg or "bc-6m-v1") / "last.pt"), **self.config}


BOTS = {"hal": HAL, "phillip": Phillip, "mimic": MIMIC, "faynt": Faynt, "reyn": ReynBot, "meleebot": MeleeBot}
