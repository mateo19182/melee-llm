"""The Brute page: it is served, its clips are the ones the page asks for, and the numbers in them hang together."""
import json
import re

import pytest
from starlette.testclient import TestClient

from melee_llm.web import server

BRUTE = server.STATIC / "brute"
SCENES = ("standoff", "reach", "door", "hop5", "coin", "walk", "turn", "retreat", "ledge")


@pytest.fixture(scope="module")
def clips():
    return json.loads((BRUTE / "clips.json").read_text())


def test_page_is_served():
    client = TestClient(server.app)
    r = client.get("/brute")
    assert r.status_code == 200 and '<a href="/brute" data-link' in r.text
    for name in ("clips.json", "status.json", "player.js"):
        assert client.get(f"/static/brute/{name}").status_code == 200
    assert client.get("/static/pages/brute.js").status_code == 200


def test_page_and_clips_name_the_same_scenes(clips):
    asked = re.findall(r'player\("(\w+)"\)', (server.STATIC / "pages" / "brute.js").read_text())
    assert tuple(asked) == SCENES == tuple(s["id"] for s in clips["scenes"])


def test_clips_are_complete(clips):
    for scene in clips["scenes"]:
        for clip in scene["clips"]:
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


def test_status_file():
    s = json.loads((BRUTE / "status.json").read_text())
    assert s["state"] in ("not_started", "running", "done")
    assert s["title"] and s["summary"] and re.fullmatch(r"\d{4}-\d\d-\d\d", s["updated"])
    assert all(set(d) == {"label", "value"} for d in s["details"]) and isinstance(s["findings"], list)
    assert all(isinstance(x, str) and x for x in s.get("next", []))
