import json
import subprocess
import sys
from unittest.mock import Mock

import pytest

from app.config import Settings
from app import Action, snapshot, step
from app.runner import next_player, random_game, replay


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


@pytest.mark.parametrize("trailing", [{"kind": "lift"}, {"kind": 2}])
def test_replay_validates_after_win_and_budget(trailing):
    data = recording()
    data["moves"][-1] = trailing
    for limit in (None, 1):
        with pytest.raises(ValueError):
            replay(data, max_turns=limit)


def test_replay_empty_and_exhaustion_at_limit():
    empty = replay({"n": 1, "turn_order": [], "moves": []})
    assert empty["stop_reason"] == "input_exhausted" and empty["turns_processed"] == 0
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
    assert Settings(max_n=10**9).budget(10**9) == 100000
    assert config.budget(3, 12) == 12
    with pytest.raises(ValueError):
        config.budget(3, 7001)
    monkeypatch.setenv("HANOI_MAX_N", "12")
    monkeypatch.setenv("HANOI_MOVES_FACTOR", "3")
    monkeypatch.setenv("HANOI_MAX_MOVES", "100")
    assert Settings.from_env().budget(3) == 21
    assert Settings.from_env().budget(12) == 100
    monkeypatch.setenv("HANOI_MAX_MOVES", "3.00")
    assert Settings.from_env().max_moves == 3
    monkeypatch.setenv("HANOI_MAX_MOVES", "3.5")
    with pytest.raises(ValueError):
        Settings.from_env()


def test_balanced_scheduler_allows_repeated_players():
    rng = Mock()
    rng.choice.side_effect = ["A", "B"]
    counts, sequence = [0, 0], []
    for _ in range(4):
        player = next_player(counts, rng)
        sequence.append(player)
        counts[player == "B"] += 1
    assert sequence == ["A", "B", "B", "A"] and counts == [2, 2]
    assert rng.choice.call_count == 2


def test_random_game_actual_transitions(monkeypatch):
    counts, kinds, states = {"A": 0, "B": 0}, set(), []

    def checked_step(state, player, action):
        counts[player] += 1
        assert abs(counts["A"] - counts["B"]) <= 1
        outcome = step(state, player, action)
        assert outcome.legal, (player, action, outcome.reason)
        if action.kind != "skip":
            assert outcome.state != state
        kinds.add(action.kind)
        states.append(outcome.state)
        return outcome

    monkeypatch.setattr("app.runner.step", checked_step)
    result = random_game((0, 3, 42, 200, 10))
    assert {"lift", "place"} <= kinds
    assert result["turns_processed"] == sum(counts.values()) == len(states)
    assert result["state"] == snapshot(states[-1]) and result["illegal_actions"] == 0


def test_random_game_reports_actual_illegal_count(monkeypatch):
    monkeypatch.setattr("app.runner.random_action", lambda *args: Action("dance"))
    result = random_game((0, 1, 42, 3, 10))
    assert result["illegal_actions"] == result["turns_processed"] == 3


def cli(*args, input=None):
    return subprocess.run([sys.executable, "-m", "app", *args], input=input,
                          text=True, capture_output=True)


def test_cli_replay_bad_input():
    bad = cli("replay", "-", input="not json")
    assert bad.returncode != 0 and "error:" in bad.stderr and "Traceback" not in bad.stderr


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


def test_cli_replay_whole_number_decimals():
    for n in (3.0, "3.00"):
        output = cli("replay", "-", input=json.dumps({"n": n, "turn_order": [], "moves": []}))
        assert output.returncode == 0, output.stderr
        assert json.loads(output.stdout)["state"]["poles"]["1a"] == [5, 3, 1]
