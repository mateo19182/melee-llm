"""Offline tests for the commentary booth: reply parsing, audio tags, KO wording."""
from types import SimpleNamespace as NS

from melee import Action as A

from melee_llm import commentary as C


def test_turns_and_tags():
    args = {"turns": [{"speaker": "Laura", "line": " [deadpan] Clean. "}, {"speaker": "Nobody", "line": "[shouting] GONE!"},
                      {"speaker": "Charlie", "line": ""}, {"speaker": "Charlie", "line": "third"}]}
    assert C.turns_of(args) == [("Laura", "[deadpan] Clean."), ("Charlie", "[shouting] GONE!")]
    assert C.turns_of(None) == [] and C.turns_of({"turns": "x"}) == []
    assert C.TAG.sub(" ", "[shouting] GONE! [laughs] Wow").strip() == "GONE! Wow"
    assert set(C.TOOL["function"]["parameters"]["properties"]["turns"]["items"]["properties"]["speaker"]["enum"]) == set(C.CASTERS)


def test_ko_names_the_killer_first():
    t = C.PlayTracker({1: "Phillip (Fox)", 2: "MIMIC (Marth)"})

    def gs(frame, pct2, stock2):
        mk = lambda pct, stock: NS(percent=pct, stock=stock, action=A.STANDING, off_stage=False, hitstun_frames_left=0)
        return NS(frame=frame, players={1: mk(0.0, 4), 2: mk(pct2, stock2)})
    t.update(gs(1, 0.0, 4))
    t.update(gs(2, 80.0, 4))
    [ev] = t.update(gs(3, 0.0, 3))
    assert ev.big and ev.text == "Phillip (Fox) KOs MIMIC (Marth) at 80%"


def test_head_to_head_from_arena_results(tmp_path, monkeypatch):
    from melee_llm import paths
    monkeypatch.setattr(paths, "ARENA", tmp_path)
    rows = [{"p1": "hal:MASTER", "p2": "mimic", "winner": 1}, {"p1": "mimic", "p2": "hal:MASTER", "winner": 1},
            {"p1": "mimic", "p2": "hal:MASTER", "winner": 2}, {"p1": "mimic", "p2": "cpu:9", "winner": 1},
            {"p1": "mimic", "p2": "hal:MASTER", "winner": None}]
    (tmp_path / "results.jsonl").write_text("".join(__import__("json").dumps(r) + "\n" for r in rows))
    assert C.head_to_head("hal:MASTER", "mimic") == "; in earlier arena games the first player won 2 and the second 1"
    assert C.head_to_head("hal:MASTER", "faynt") == "" and C.head_to_head(None, "mimic") == ""
    assert C._clock(3725) == "1:02"
