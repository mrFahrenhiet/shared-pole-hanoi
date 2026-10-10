import json
import random
import subprocess
import sys

import pytest

from hanoi.runner import Settings, next_player, random_games, replay


def recording():
    return {"n": "1", "turn_order": ["A", "B", "A", "B"],
            "moves": [{"kind": "lift", "pole": "1a"},
                      {"kind": "lift", "pole": "1b"},
                      {"kind": "place", "pole": "3a"}, {"kind": "skip"}]}


def test_replay_win_and_unused_moves():
    result = replay(recording())
    assert result["winner"] == "A" and result["turns_processed"] == 3
    assert result["unused_moves"] == 1 and result["stop_reason"] == "win"
    assert result["state"]["hands"] == {"A": 0, "B": 2}


def test_replay_illegal_turns_count_and_do_not_mutate():
    data = {"n": 1, "turn_order": ["B"] * 4,
            "moves": [{"kind": "lift", "pole": "1a"},
                      {"kind": "place", "pole": "3a"},
                      {"kind": "dance"}, {"kind": "lift", "pole": "unknown"}]}
    result = replay(data)
    assert result["illegal_actions"] == result["turns_processed"] == 4
    assert result["state"]["poles"]["1a"] == [1]
    assert result["state"]["poles"]["1b"] == [2]


@pytest.mark.parametrize("data", [None, {}, {**recording(), "extra": 1},
    {**recording(), "turn_order": ["A"]}, {**recording(), "turn_order": ["C"] * 4},
    {**recording(), "moves": [{}] * 4}, {**recording(), "moves": [{"kind": 2}] * 4},
    {**recording(), "moves": [{"kind": "lift"}] * 4},
    {**recording(), "moves": [{"kind": "lift", "pole": 1}] * 4},
    {**recording(), "moves": [{"kind": "skip", "pole": "2"}] * 4},
    {**recording(), "moves": [{"kind": "skip", "extra": 1}] * 4}])
def test_malformed_replay(data):
    with pytest.raises(ValueError):
        replay(data)


def test_replay_empty_limit_and_win_precedence():
    empty = replay({"n": 1, "turn_order": [], "moves": []})
    assert empty["stop_reason"] == "input_exhausted" and empty["turns_processed"] == 0
    limited = replay(recording(), max_turns=2)
    assert limited["stop_reason"] == "move_limit" and limited["unused_moves"] == 2
    assert replay(recording(), max_turns=3)["stop_reason"] == "win"
    skips = {"n": 1, "turn_order": ["A"], "moves": [{"kind": "skip"}]}
    assert replay(skips, max_turns=1)["stop_reason"] == "move_limit"


def test_settings_and_budgets(monkeypatch):
    for key in ("HANOI_MAX_N", "HANOI_MOVES_FACTOR", "HANOI_MAX_MOVES"):
        monkeypatch.delenv(key, raising=False)
    config = Settings.from_env()
    assert config == Settings(10, 1000, 100000)
    assert config.budget("1") == 1000
    assert config.budget(3) == 7000
    assert config.budget(10) == 100000
    assert config.budget(3, 12) == 12
    with pytest.raises(ValueError):
        config.budget(3, 7001)
    monkeypatch.setenv("HANOI_MAX_N", "12")
    monkeypatch.setenv("HANOI_MOVES_FACTOR", "3")
    monkeypatch.setenv("HANOI_MAX_MOVES", "100")
    assert Settings.from_env().budget(3) == 21
    assert Settings.from_env().budget(12) == 100
    monkeypatch.setenv("HANOI_MAX_MOVES", "3.0")
    with pytest.raises(ValueError):
        Settings.from_env()


def test_balanced_scheduler_allows_repeated_players():
    saw_abba = False
    for seed in range(40):
        rng = random.Random(seed)
        counts = [0, 0]
        sequence = []
        for _ in range(100):
            player = next_player(counts, rng)
            sequence.append(player)
            counts[player == "B"] += 1
            assert abs(counts[0] - counts[1]) <= 1
        saw_abba |= sequence[:4] == ["A", "B", "B", "A"]
    assert saw_abba


def test_seeded_parallel_games_match_and_are_isolated():
    serial = list(random_games(2, 25, 1, 42, max_turns=100))
    parallel = list(random_games(2, 25, 3, 42, max_turns=100))
    assert parallel == serial
    assert [r["game_index"] for r in serial] == list(range(25))
    assert all(r["illegal_actions"] == 0 for r in serial)
    assert serial[1]["state"] == list(random_games(2, 1, 1, 43, max_turns=100))[0]["state"]


def cli(*args, input=None):
    return subprocess.run([sys.executable, "-m", "hanoi", *args], input=input,
                          text=True, capture_output=True)


def test_cli_replay_stdin_and_bad_input():
    output = cli("replay", "-", input=json.dumps(recording()))
    assert output.returncode == 0 and json.loads(output.stdout)["winner"] == "A"
    bad = cli("replay", "-", input="not json")
    assert bad.returncode != 0 and "error:" in bad.stderr and "Traceback" not in bad.stderr


def test_cli_random_jsonl_and_validation():
    output = cli("random-play", "2", "--games", "4", "--workers", "2",
                 "--seed", "42", "--max-turns", "1")
    assert output.returncode == 0, output.stderr
    records = [json.loads(line) for line in output.stdout.splitlines()]
    assert len(records) == 5
    assert records[-1]["type"] == "summary" and records[-1]["move_limit"] == 4
    assert records[-1]["base_seed"] == 42
    for args in [("1.0",), ("11",), ("1", "--workers", "0"),
                 ("1", "--max-turns", "1001")]:
        assert cli("random-play", *args).returncode != 0


def test_cli_environment_limits_both_frontends(monkeypatch):
    monkeypatch.setenv("HANOI_MAX_N", "10")
    monkeypatch.setenv("HANOI_MOVES_FACTOR", "1")
    monkeypatch.setenv("HANOI_MAX_MOVES", "1")
    output = cli("replay", "-", input=json.dumps(recording()))
    assert output.returncode == 0
    assert json.loads(output.stdout)["stop_reason"] == "move_limit"
    assert json.loads(output.stdout)["turns_processed"] == 1
    for n in ("1", "10"):
        output = cli("random-play", n, "--seed", "1")
        assert output.returncode == 0, output.stderr
        game = json.loads(output.stdout.splitlines()[0])
        assert game["turns_processed"] == 1 and game["stop_reason"] == "move_limit"
    monkeypatch.setenv("HANOI_MAX_N", "invalid")
    assert cli("random-play", "1").returncode != 0
