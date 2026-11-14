"""The stomped bot reads the event stream exactly as the dataset builder reads the .slp file.

    cd train && uv run --with pytest python -m pytest tests
"""
import glob, struct

import numpy as np
import pytest

from meleebot import stomped
from meleebot.build_dataset import parse
from meleebot.schema import FRAME
from meleebot.stomped_arena import slp_messages

REPLAYS = sorted(glob.glob("/mnt/data/melee/ranked-replays/slp/YOSHI/*.slp"))[:3]


def _stream(path):
    """Every message stomped would send for this replay, through the bot's reader."""
    brain = stomped.Brain.__new__(stomped.Brain)
    brain.raw, ev = {}, stomped.Events()
    for msg in slp_messages(path):
        for cmd, b in ev.feed(msg):
            brain.on_event(cmd, b)
    return brain.raw


@pytest.mark.skipif(not REPLAYS, reason="no replays on this machine")
@pytest.mark.parametrize("path", REPLAYS)
def test_stream_matches_dataset(path):
    _, out = parse((path, "ALL"))
    assert not isinstance(out, str), out
    raw = _stream(path)
    ports = sorted({k[1] for k in raw if k[0] != "pad"})  # parse() yields perspectives in port order
    for me, (blob, _) in enumerate(out):
        stored = np.frombuffer(blob, FRAME)
        p, o = ports[me], ports[1 - me]
        live = np.zeros(len(stored), FRAME)
        for i in range(len(stored)):
            live[i]["me"], live[i]["opp"] = raw[(i, p)], raw[(i, o)]
            live[i]["me_pad"], live[i]["opp_pad"] = raw[("pad", i, p)], raw[("pad", i, o)]
        for side in ("me", "opp", "me_pad", "opp_pad"):
            for field in stored.dtype[side].names:
                a, b = live[side][field], stored[side][field]
                assert np.array_equal(a, b), (side, field, int((a != b).reshape(len(a), -1).any(1).sum()))


def test_wire_layout():
    c = np.zeros((), FRAME["me_pad"])
    c["stick"], c["cstick"], c["trigger"], c["buttons"] = (80, -80), (0, 56), (140, 0), 0x0140
    assert stomped.wire(7, c) == struct.pack("<iH6B", 7, 0x0140, 208, 48, 128, 184, 140, 0)
    assert stomped.wire(-123, stomped.NEUTRAL) == struct.pack("<iH6B", -123, 0, 128, 128, 128, 128, 0, 0)


def test_choice_to_pad():
    centers = np.array([[0, 0], [80, 0], [0, -80]])
    pad = stomped.choice_to_pad(dict(stick=1, cstick=3, buttons=0b10001, shoulder=0), centers)
    assert tuple(pad["stick"]) == (80, 0) and tuple(pad["cstick"]) == (0, 80)
    assert pad["buttons"] == 0x0100 | 0x0040 and tuple(pad["trigger"]) == (140, 0)  # A + full shield
    light = stomped.choice_to_pad(dict(stick=0, cstick=0, buttons=0, shoulder=1), centers)
    assert light["buttons"] == 0 and tuple(light["trigger"]) == (60, 0)


@pytest.mark.parametrize("rtt,compute,lead", [(1, 4, 2), (6, 4, 2), (6, 6, 3), (135, 4, 10), (25, 0, 3)])
def test_lead(rtt, compute, lead):
    assert stomped.lead_for(rtt, compute) == lead
