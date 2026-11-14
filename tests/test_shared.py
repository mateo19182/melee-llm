"""Offline tests for the shared modules: player specs, jsonl helpers, child game processes."""
import sys

import melee
import pytest

from melee_llm import players, util


def test_every_kind_builds_with_its_character():
    for kind in players.KINDS:
        spec = f"{kind}:claude-haiku-4-5-20251001" if kind.startswith("llm_") else kind
        assert players.make(spec, "MARTH").character == melee.Character.MARTH, kind
    cpu = players.make("cpu:7", melee.Character.FALCO)
    assert (cpu.cpu_level, cpu.character) == (7, melee.Character.FALCO)
    assert players.make("cpu", "FOX").cpu_level == 9
    with pytest.raises(KeyError):
        players.make("nope", "FOX")


def test_log_dir_reaches_players_that_log(tmp_path):
    assert players.make("llm_paused:m", "FOX", tmp_path).log_dir == tmp_path
    assert not hasattr(players.make("idle", "FOX", tmp_path), "log_dir")
    bot = players.make("baseline:rusher", "FOX", tmp_path)
    assert bot.name == "baseline:rusher"


def test_bot_games_do_not_import_the_llm_client():
    code = ("import sys; from melee_llm.players import make; make('hal:MASTER', 'FOX'); make('cpu:9', 'FOX'); "
            "print('openai' in sys.modules)")
    import subprocess
    assert subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, cwd=util.ROOT).stdout.strip() == "False"


def test_jsonl_skips_torn_lines(tmp_path):
    path = tmp_path / "r.jsonl"
    assert util.read_jsonl(path) == []
    util.append_jsonl(path, {"a": 1})
    with path.open("a") as f:
        f.write('{"b": 2}\n{"c": \n')  # the last line is still being written
    assert util.read_jsonl(path) == [{"a": 1}, {"b": 2}]


def test_write_atomic_replaces(tmp_path):
    path = tmp_path / "sub/s.json"
    util.write_atomic(path, "1")
    util.write_atomic(path, "2")
    assert path.read_text() == "2" and [p.name for p in path.parent.iterdir()] == ["s.json"]


def test_game_process_result_is_the_last_json_line():
    code = "import sys; print('noise'); print('{\"winner\": 1}'); print('bye'); print('warn', file=sys.stderr)"
    res, out, err, timed_out = util.run_game_process([sys.executable, "-c", code], timeout=30)
    assert res == {"winner": 1} and "noise" in out and "warn" in err and not timed_out
    res, _, err, timed_out = util.run_game_process([sys.executable, "-c", "raise SystemExit('boom')"], timeout=30)
    assert res is None and "boom" in err and not timed_out


def test_game_process_timeout_kills_the_group(tmp_path):
    # the child starts a grandchild (as play() starts Dolphin) that would outlive a plain kill of the child
    code = ("import subprocess, sys, time; "
            f"p = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)']); open({str(tmp_path / 'pid')!r}, 'w').write(str(p.pid)); "
            "time.sleep(60)")
    res, out, _, timed_out = util.run_game_process([sys.executable, "-c", code], timeout=2, grace=5)
    assert res is None and out == "" and timed_out
    import os
    import time
    pid = int((tmp_path / "pid").read_text())
    for _ in range(50):
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            break
        time.sleep(0.1)
    else:
        pytest.fail("the grandchild survived the timeout")


def test_port_free():
    import socket
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        s.bind(("127.0.0.1", 0))
        assert not util.port_free(s.getsockname()[1])
