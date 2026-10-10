"""Check generated high-N and edge-case recordings without stored artifacts."""
import json

import pytest

from app.runner import replay
from test_runner import cli

CASES = [
    ("n1_a_wins.json", "A", 3, 0, 0),
    ("n2_b_wins.json", "B", 6, 0, 0),
    ("n3_a_wins.json", "A", 14, 0, 0),
    ("n5_alternating_a_wins.json", "A", 123, 0, 0),
    ("n10_b_wins.json", "B", 2046, 0, 0),
    ("n3_illegal_moves.json", None, 6, 2, 0),
    ("n1_shared_blocks_win.json", None, 4, 0, 0),
    ("n1_opponent_wins_early.json", "A", 5, 0, 2),
    ("n2_shared_disk_transfer.json", None, 4, 0, 0),
    ("n10_empty_recording.json", None, 0, 0, 0),
]


@pytest.mark.parametrize("filename,winner,turns,illegal,unused", CASES)
def test_recorded_example(examples, filename, winner, turns, illegal, unused):
    data = json.loads((examples / filename).read_text())
    outcome = replay(data)
    assert (outcome["winner"], outcome["turns_processed"],
            outcome["illegal_actions"], outcome["unused_moves"]) == (winner, turns, illegal, unused)
    assert outcome["stop_reason"] == ("win" if winner else "input_exhausted")
    poles, hands = outcome["state"]["poles"], outcome["state"]["hands"]
    if filename in ("n3_a_wins.json", "n5_alternating_a_wins.json", "n10_b_wins.json"):
        n = data["n"]
        largest = 2 * n - (winner == "A")
        assert poles["3" + winner.lower()] == list(range(largest, 0, -2))
        assert not poles["2"] and not poles["1" + winner.lower()] and hands[winner] == 0
    if filename == "n5_alternating_a_wins.json":
        assert data["turn_order"] == ["A", "B"] * 61 + ["A"]
    if filename == "n1_shared_blocks_win.json":
        assert poles["3a"] == [1] and poles["2"] == [2] and hands["A"] == 0
    if filename == "n1_opponent_wins_early.json":
        assert data["turn_order"][turns - 1] == "B" and hands["B"] == 2
    if filename == "n2_shared_disk_transfer.json":
        assert poles["3a"] == [2] and poles["1a"] == [3, 1] and poles["1b"] == [4]


@pytest.mark.parametrize("filename,error", [
    ("fractional_n.json", "positive integer"),
    ("n_above_max.json", "must not exceed 10"),
    ("mismatched_turns.json", "equally sized lists"),
])
def test_invalid_example(examples, filename, error):
    data = json.loads((examples / "invalid" / filename).read_text())
    with pytest.raises(ValueError, match=error):
        replay(data)


def test_examples_cli_batch_smoke(examples):
    paths = sorted(examples.glob("*.json")) + sorted((examples / "invalid").glob("*.json"))
    output = cli("replay", *map(str, paths), "--workers", "99")
    assert output.returncode == 1 and "Traceback" not in output.stderr
    *games, summary = [json.loads(line) for line in output.stdout.splitlines()]
    assert len(games) == 13
    assert summary == {"type": "summary", "games": 13, "succeeded": 10, "failed": 3,
                       "wins": {"A": 4, "B": 2},
                       "stop_reasons": {"win": 6, "move_limit": 0, "input_exhausted": 4}}


def test_example_win_on_budget_boundary(examples):
    data = json.loads((examples / "n3_a_wins.json").read_text())
    limited = replay(data, max_turns=13)
    assert limited["stop_reason"] == "move_limit" and limited["winner"] is None
    assert limited["unused_moves"] == 1 and limited["state"]["hands"]["A"] == 1
    completed = replay(data, max_turns=14)
    assert completed["stop_reason"] == "win" and completed["winner"] == "A"


def test_published_example_is_self_contained_and_reproducible():
    serial = cli("batch", "examples/example.json", "--workers", "1")
    parallel = cli("batch", "examples/example.json", "--workers", "2")
    assert serial.returncode == parallel.returncode == 0
    assert serial.stdout == parallel.stdout
    summary = json.loads(serial.stdout.splitlines()[-1])
    assert summary["games"] == summary["succeeded"] == 7 and summary["failed"] == 0
