"""Player specs for the launcher: what can be picked, labels, and per-bot validation (no heavy imports)."""
from __future__ import annotations

import json
import time
from functools import lru_cache

from melee_llm.web.paths import ROOT

VENDOR = ROOT / "vendor"
CHARACTERS = ["FOX", "FALCO", "MARTH", "SHEIK", "CPTFALCON", "JIGGLYPUFF", "PEACH", "POPO", "SAMUS", "GANONDORF",
              "LUIGI", "MARIO", "DOC", "YOSHI", "DK", "LINK", "YLINK", "NESS", "PIKACHU", "PICHU", "ROY", "MEWTWO",
              "GAMEANDWATCH", "KIRBY", "BOWSER", "ZELDA"]
STAGES = ["BATTLEFIELD", "FINAL_DESTINATION", "YOSHIS_STORY", "DREAMLAND", "FOUNTAIN_OF_DREAMS", "POKEMON_STADIUM"]
MODES = {"lockstep": "rendered, live; game waits for each input (real time with fast bots)",
         "paused": "rendered, live; same as lockstep, meant for slow LLM players",
         "fast": "headless and unthrottled, not shown live; up to 4 run in parallel"}
CHAR_NAMES = {"CPTFALCON": "Falcon", "JIGGLYPUFF": "Puff", "POPO": "Ice Climbers", "DK": "DK", "YLINK": "Young Link",
              "GAMEANDWATCH": "G&W", "DOC": "Dr. Mario"}
LEARNED = {"hal", "phillip", "mimic", "faynt", "reyn"}
MIMIC_CHARS = {"fox": "FOX", "falco": "FALCO", "marth": "MARTH", "sheik": "SHEIK", "cptfalcon": "CPTFALCON",
               "puff": "JIGGLYPUFF", "luigi": "LUIGI", "peach": "PEACH"}
COACH_ALIASES = ["haiku", "sonnet", "random"]


def char_name(c: str) -> str:
    return CHAR_NAMES.get(c, c.replace("_", " ").title())


def stage_name(s: str) -> str:
    return s.replace("_", " ").title().replace("Yoshis", "Yoshi's")


def short_model(m: str) -> str:
    for pre in ("claude-",):
        m = m.removeprefix(pre)
    return m.removesuffix("-20251001").removesuffix("-20250929")


def label(spec: str) -> str:
    """Human name for a player spec: cpu:9 → CPU 9, llm_paused:claude-haiku-… → LLM haiku-4-5 (paused)."""
    kind, _, arg = spec.partition(":")
    head, *opts = arg.split(",") if arg else [""]
    if kind == "cpu":
        return f"CPU {arg or 9}"
    if kind in ("llm_paused", "llm_live"):
        return f"LLM {short_model(head)}" + (" (live)" if kind == "llm_live" else "")
    if kind == "coach":
        body = next((o.split("=", 1)[1] for o in opts if o.startswith("body=")), "reyn")
        return f"Coach {short_model(head) or 'haiku'} → {body.title() if body != 'hal' else 'HAL'}"
    names = {"hal": "HAL", "phillip": "Phillip", "mimic": "MIMIC", "faynt": "Faynt", "reyn": "Reyn"}
    if kind in names:
        if kind == "reyn" and arg:
            return f'Reyn "{arg[:30]}"'
        return names[kind] + (f" {arg}" if arg and kind != "reyn" else "")
    return spec


def kind_of(spec: str) -> str:
    kind = spec.partition(":")[0]
    return "bot" if kind in LEARNED else kind


@lru_cache(maxsize=1)
def phillip_models() -> dict[str, list[str]]:
    """model name → characters it plays."""
    models = VENDOR / "slippi-ai/models"
    index = {}
    try:
        for m in json.loads((models / "index-v1.json").read_text())["models"]:
            index[m["name"]] = m.get("characters") or []
    except (OSError, ValueError, KeyError):
        pass
    out = {}
    for f in sorted(models.glob("*.onnx")):
        chars = index.get(f.stem)
        if not chars:
            prefix = f.stem.split("_")[0].upper()
            chars = [prefix] if prefix in CHARACTERS else CHARACTERS
        out[f.stem] = chars
    return out


def mimic_checkpoints() -> dict[str, str]:
    """checkpoint dir → character."""
    root = VENDOR / "MIMIC/hf_checkpoints"
    out = {}
    for d in sorted(p for p in root.glob("*") if p.is_dir()) if root.exists() else []:
        char = MIMIC_CHARS.get(d.name.split("-")[0])
        if char:
            out[d.name] = char
    return out


def faynt_variants() -> list[str]:
    root = VENDOR / "Faynt-Tournament/weights"
    return sorted(p.name.removeprefix("Faynt-") for p in root.glob("Faynt-*")) if root.exists() else []


_models: tuple[float, list[str]] = (0.0, [])


def llm_models() -> list[str]:
    """CLIProxy chat models (cached 5 min); image models are left out."""
    global _models
    if time.time() - _models[0] > 300 or not _models[1]:
        try:
            from melee_llm.llm import list_models
            ids = [m for m in list_models() if "image" not in m]
            _models = (time.time(), ids)
        except Exception:  # proxy down: keep the last list
            _models = (time.time() - 240, _models[1])
    return _models[1]


def catalog() -> dict:
    models = llm_models()
    default_model = "claude-haiku-4-5-20251001" if "claude-haiku-4-5-20251001" in models else (models[0] if models else "")
    mimic = mimic_checkpoints()
    return {
        "kinds": [
            {"kind": "cpu", "label": "In-game CPU", "arg": {"type": "select", "options": [str(i) for i in range(1, 10)],
                                                          "default": "9"}},
            {"kind": "llm_paused", "label": "LLM player, paused (game waits while it thinks)",
             "arg": {"type": "select", "options": models, "default": default_model}, "options": "interval=30,history=6",
             "mode": "paused"},
            {"kind": "llm_live", "label": "LLM player, live (thinks in the background)",
             "arg": {"type": "select", "options": models, "default": default_model}, "options": "interval=30,max_stale=120"},
            {"kind": "coach", "label": "LLM coach steering a learned bot",
             "arg": {"type": "select", "options": COACH_ALIASES + models, "default": "haiku"},
             "options": "body=reyn,interval=120"},
            {"kind": "hal", "label": "HAL (250M transformer)",
             "arg": {"type": "text", "options": ["MASTER", "DIAMOND", "PLATINUM"], "default": "MASTER",
                     "placeholder": "MASTER, DIAMOND, PLATINUM or a connect code"}},
            {"kind": "phillip", "label": "Phillip (slippi-ai)", "arg": {"type": "select", "options": list(phillip_models()),
                                                                     "default": "gm"}},
            {"kind": "mimic", "label": "MIMIC", "arg": {"type": "select", "options": [""] + list(mimic), "default": "",
                                                       "blank": "checkpoint for the character"}},
            {"kind": "faynt", "label": "Faynt", "arg": {"type": "select", "options": faynt_variants(), "default": "10M-Arena"}},
            {"kind": "reyn", "label": "Reyn (language-steerable)",
             "arg": {"type": "text", "default": "", "placeholder": "optional command, e.g. Be more aggressive."}},
            {"kind": "shine", "label": "Multishine demo"},
            {"kind": "idle", "label": "Idle (does nothing)"},
        ],
        "characters": [{"id": c, "name": char_name(c)} for c in CHARACTERS],
        "stages": [{"id": s, "name": stage_name(s)} for s in STAGES],
        "modes": [{"id": k, "desc": v} for k, v in MODES.items()],
        "constraints": {"phillip": phillip_models(), "mimic": mimic},
        "models": models,
    }


def validate(p1: str, p2: str, char1: str, char2: str, stage: str, mode: str, games: int) -> tuple[list[str], list[str]]:
    """(errors, warnings) for a match request."""
    errors, warnings = [], []
    if mode not in MODES:
        errors.append(f"unknown mode {mode}")
    if stage not in STAGES:
        errors.append(f"unknown stage {stage}")
    if not 1 <= games <= 50:
        errors.append("games must be 1-50")
    for port, spec, char in ((1, p1, char1), (2, p2, char2)):
        who = f"P{port} ({label(spec)})"
        if char not in CHARACTERS:
            errors.append(f"{who}: unknown character {char}")
            continue
        kind, _, arg = spec.partition(":")
        head = arg.split(",")[0]
        if kind == "cpu":
            if not (arg or "9").isdigit() or not 1 <= int(arg or 9) <= 9:
                errors.append(f"{who}: CPU level must be 1-9")
        elif kind in ("llm_paused", "llm_live", "coach"):
            models = llm_models()
            ok = head in models or (kind == "coach" and head in COACH_ALIASES + [""])
            if not ok and models:
                errors.append(f"{who}: model {head!r} is not offered by the proxy")
            if kind == "llm_paused" and mode not in ("paused", "lockstep", "fast"):
                errors.append(f"{who}: llm_paused blocks the game; use paused mode")
            if kind == "llm_live" and mode == "fast":
                warnings.append(f"{who}: llm_live in fast mode decides on very stale states")
            if kind == "coach":
                body = next((o.split("=", 1)[1] for o in arg.split(",")[1:] if o.startswith("body=")), "reyn")
                if body not in ("reyn", "hal"):
                    errors.append(f"{who}: coach body must be reyn or hal")
                if body == "reyn" and mode != "fast":
                    warnings.append(f"{who}: Reyn runs at 15-60 fps, the live view may look slow")
        elif kind == "hal":
            if port not in (1, 2):
                errors.append(f"{who}: HAL only plays on ports 1 and 2")
        elif kind == "phillip":
            models = phillip_models()
            name = arg or "gm"
            if name not in models:
                errors.append(f"{who}: no Phillip model {name!r}")
            elif char not in models[name]:
                errors.append(f"{who}: Phillip {name} plays {', '.join(map(char_name, models[name]))}, not {char_name(char)}")
        elif kind == "mimic":
            ckpts = mimic_checkpoints()
            if arg:
                if arg not in ckpts:
                    errors.append(f"{who}: no MIMIC checkpoint {arg!r}")
                elif ckpts[arg] != char:
                    errors.append(f"{who}: MIMIC checkpoint {arg} plays {char_name(ckpts[arg])}")
            elif char not in ckpts.values():
                have = sorted({char_name(c) for c in ckpts.values()})
                errors.append(f"{who}: MIMIC has checkpoints for {', '.join(have)} only")
            if char == "JIGGLYPUFF":
                warnings.append(f"{who}: MIMIC's puff checkpoint uses an older schema and may not load")
        elif kind == "faynt":
            if arg and arg not in faynt_variants():
                errors.append(f"{who}: no Faynt variant {arg!r}")
            if arg.startswith("75M") and mode != "fast":
                warnings.append(f"{who}: Faynt 75M is too slow for real time")
        elif kind not in ("reyn", "shine", "idle"):
            errors.append(f"{who}: unknown player kind {kind!r}")
        if kind in LEARNED and mode == "watch":
            errors.append(f"{who}: learned bots need lockstep or fast mode")
    return errors, warnings
