"""The Brute page: it is served, its clips are the ones the page asks for, and the numbers in them hang together."""
import json
import re

import pytest
from starlette.testclient import TestClient

from melee_llm.web import server

BRUTE = server.STATIC / "brute"
SCENES = ("standoff", "reach", "walk", "turn", "door", "hop5", "coin", "retreat", "ledge")
PAGE = server.STATIC / "pages" / "brute.js"


@pytest.fixture(scope="module")
def clips():
    return json.loads((BRUTE / "clips.json").read_text())


def test_page_is_served():
    client = TestClient(server.app)
    r = client.get("/brute")
    assert r.status_code == 200 and '<a href="/brute" data-link' in r.text
    for name in ("clips.json", "status.json", "road.json", "player.js"):
        assert client.get(f"/static/brute/{name}").status_code == 200
    assert client.get("/static/pages/brute.js").status_code == 200


def test_page_and_clips_name_the_same_scenes(clips):
    asked = re.findall(r'player\("(\w+)"\)', PAGE.read_text())
    assert tuple(asked) == SCENES == tuple(s["id"] for s in clips["scenes"])


def test_clips_are_complete(clips):
    for scene in clips["scenes"]:
        for clip in scene["clips"] + ([scene["setup"]] if "setup" in scene else []):
            where = f"{scene['id']}/{clip['id']}"
            assert clip["title"] and clip["caption"] and clip["notes"], where
            assert len(clip["rows"]) > 1 and all(len(p) == 12 for row in clip["rows"] for p in row), where
            assert all(str(p[2]) in clips["actions"] for row in clip["rows"] for p in row), where
            assert not re.search(r"orange", json.dumps([clip["title"], clip["caption"], clip["notes"]]), re.I), where


def test_clips_can_be_drawn_as_fox(clips):
    """The page draws each Fox with Slippi Lab's renderer: a row gives it an action, its frame and a facing, and the
    renderer in the patch has every function the player calls."""
    for scene in clips["scenes"]:
        for clip in scene["clips"]:
            for row in clip["rows"]:
                for p in row:
                    assert isinstance(p[2], int) and isinstance(p[3], int) and p[3] >= -1 and p[4] in (0, 1), clip["id"]
    player = (BRUTE / "player.js").read_text()
    patch = (server.ROOT / "patches" / "slippilab.patch").read_text()
    assert 'import("/slippilab-live.js")' in player
    used = set(re.findall(r"\b(?:R\??|m)\.(draw\w+|preload)\b", player))
    assert used == {"drawFighter", "drawShield", "drawShine", "preload"}
    for name in used:
        assert f"+export function {name}(" in patch, name
    assert "+export const STAGES" in patch and "R?.STAGES.FINAL_DESTINATION" in player


def hits(clip):
    """(frame, player, percent) for every frame on which someone's percent went up, as the page counts them."""
    rows = clip["rows"]
    return [(i - clip["lead"], p + 1, round(rows[i][p][5] - rows[i - 1][p][5], 1))
            for i in range(1, len(rows)) for p in (0, 1) if rows[i][p][5] > rows[i - 1][p][5]]


def test_guesses_show_their_mix(clips):
    """A guess has both mixes in percent, a value that follows from them, and one clip per pair of inputs."""
    want = {"coin": 0.5, "turn": 0.25, "ledge": 0.5}
    grids = {s["id"]: s for s in clips["scenes"] if "grid" in s}
    assert set(grids) == set(want)
    for name, scene in grids.items():
        g = scene["grid"]
        rows, cols = [r["p"] for r in g["rows"]], [c["p"] for c in g["cols"]]
        assert sum(rows) == sum(cols) == 100 and g["value"] == want[name]
        assert len(scene["clips"]) == len(rows) * len(cols)
        cells = [[scene["clips"][i * len(cols) + j] for j in range(len(cols))] for i in range(len(rows))]
        assert [[c["value"] for c in row] for row in cells] == g["cells"]
        # whichever input one side picks, the other's mix gives the attacker exactly the value
        for i in range(len(rows)):
            assert sum(cols[j] * g["cells"][i][j] for j in range(len(cols))) / 100 == pytest.approx(g["value"])
        for j in range(len(cols)):
            assert sum(rows[i] * g["cells"][i][j] for i in range(len(rows))) / 100 == pytest.approx(g["value"])
        for clip in scene["clips"]:  # red scores 1 only where blue alone is hit or leaves the stage
            hit = hits(clip)
            off = any(abs(row[1][0]) > clips["ledge"] for row in clip["rows"])
            assert (clip["value"] == 1) == ((bool(hit) and all(h[1] == 2 for h in hit)) or (off and not hit)), clip["id"]


def test_story_numbers(clips):
    scene = {s["id"]: {c["id"]: c for c in s["clips"]} for s in clips["scenes"]}
    gap = lambda clip, frame: round(clip["rows"][frame + clip["lead"]][1][0] - clip["rows"][frame + clip["lead"]][0][0], 2)
    assert gap(scene["standoff"]["wait"], 0) == 12.59 and not hits(scene["standoff"]["wait"])
    for clip in scene["door"].values():  # every exit from shield is hit, from 14.39
        assert gap(clip, 0) == 14.39 and [h[1] for h in hits(clip)] == [2], clip["id"]
    for clip in scene["hop5"].values():  # the hop five frames in: the defender is hit whatever he does
        assert gap(clip, 0) == 9.42 and [h[1:] for h in hits(clip)] == [(2, 5.0)], clip["id"]
    walk = scene["walk"]["walk"]  # 182 frames of walking from the match start, then the flick
    assert (gap(walk, 0), gap(walk, 182), gap(walk, 183), len(walk["rows"])) == (120.0, 13.71, 13.19, 184) and not hits(walk)
    back = scene["retreat"]["back"]
    assert not hits(back) and round(clips["ledge"] - back["rows"][-1][1][0], 2) == 3.95
    assert all(gap(c, 0) == 8.52 and round(c["rows"][0][1][0], 2) == clips["ledge"] for c in scene["ledge"].values())


def test_lead_ins_from_the_match_start(clips):
    """A placed position comes with the recording of how it was placed: from the match start, nobody hit, ending
    exactly where the scene's clips begin. The page quotes its phases, so they have to be in order."""
    setups = {s["id"]: (s["setup"], s["clips"][0]) for s in clips["scenes"] if "setup" in s}
    assert set(setups) == {"standoff", "door", "hop5", "coin", "ledge"}
    for name, (setup, first) in setups.items():
        frames, rows, f = setup["frames"], setup["rows"], setup["facts"]
        assert len(frames) == len(rows) and frames == sorted(set(frames)) and frames[0] == 0 and frames[-1] == f["frames"], name
        assert [p[0] for p in rows[0]] == [-60.0, 60.0] and all(p[5] == 0 for row in rows for p in row), name
        assert all(note_frame in frames for note_frame, _ in setup["notes"]), name
        assert 0 < f["walked"] < f["faced"] < f["released"] < f["stood"] <= f["frames"], name
        assert round(clips["ledge"] - rows[-1][1][0], 2) == f["room"], name
        start = first["rows"][max(first["lead"], 0)]  # frame 0 of the scene's clips
        assert [p[:3] for p in rows[-1]] == [p[:3] for p in start], name
    facts = {name: setup["facts"] for name, (setup, _) in setups.items()}
    assert (facts["standoff"]["frames"], facts["standoff"]["room"], facts["standoff"]["standing"]) == (324, 9.73, 12.59)
    assert facts["hop5"]["standing"] == facts["coin"]["standing"] == 10.19  # the hop starts inside shine range (10.7)
    assert (facts["ledge"]["room"], facts["ledge"]["standing"]) == (0.0, 8.52)
    page = PAGE.read_text()  # the pins on the road sit where the clips say
    for gap in (14.39, 13.71, 13.19, 12.59, 10.19, 8.52):
        assert f"[{gap}, " in page, gap


def test_road(clips):
    """The road diagram is section 15's raw map; what the page says about its bands holds in every cell."""
    road = json.loads((BRUTE / "road.json").read_text())
    cells = road["cells"]
    assert len(cells) == 45 and road["frames"] == 8 and road["jobs"] == 90 and round(road["positions"] / 1e9, 1) == 1.2
    assert all(c["held"] for c in cells)  # "blue loses 3 units behind his spot" changes no cell
    safe = lambda kind, lo, hi: {c["gap"]: set(c["safe"]) for c in cells if c["kind"] == kind and lo <= c["gap"] <= hi}
    assert all("wait" in c["safe"] and len(c["safe"]) > 2 for c in cells if c["gap"] >= 14.6)
    assert safe("walk", 13.4, 14.1) == {14.07: {"out", "walk_out"}, 13.47: {"out", "walk_out"}}
    assert all("wait" not in s for s in safe("walk", 12.8, 14.1).values()) and len(safe("walk", 12.8, 14.1)) == 3
    assert all("wait" not in s and {"out", "jab"} <= s for s in safe("dash", 12.3, 13.6).values())
    assert all({"wait", "out"} <= s for s in safe("stand", 12.7, 13.4).values()) and len(safe("stand", 12.7, 13.4)) == 2
    assert safe("stand", 11.5, 12.2) == {12.11: set(), 11.51: set()}
    assert [c["gap"] for c in cells if not c["safe"]] == [12.11, 11.51]
    assert all(s == {"shine"} for s in {**safe("stand", 0, 11), **safe("walk", 0, 11.7)}.values())
    assert min(safe("walk", 0, 11.7)) == 9.87 and all("wait" in s for s in safe("dash", 0, 11.8).values())
    assert not any("shield" in c["safe"] and len(c["safe"]) == 1 for c in cells)
    net = {n["attacker"]: n for n in road["net"]}
    assert (net["standing"]["gap"], net["walk_slow"]["gap"]) == (12.11, 13.9)
    for n in net.values():
        assert n["value"] == 0 and n["frames"] == 8 and n["p1"] == n["p2"] == {"wait": 1.0}


def test_status_file():
    s = json.loads((BRUTE / "status.json").read_text())
    assert s["state"] in ("not_started", "running", "done")
    assert s["title"] and s["summary"] and re.fullmatch(r"\d{4}-\d\d-\d\d", s["updated"])
    assert all(set(d) == {"label", "value"} for d in s["details"]) and isinstance(s["findings"], list)
    assert all(isinstance(x, str) and x for x in s.get("next", []))
