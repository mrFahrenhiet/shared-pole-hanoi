import json

import pytest

from app.config import Settings
from app.runner import random_games
from test_runner import cli


def test_multi_n_serial_parallel_and_single_n_compatibility(monkeypatch):
    monkeypatch.setattr("app.runner.os.process_cpu_count", lambda: 3)
    serial = list(random_games([1.0, "2.00", 3], 5, 1, 42, max_turns=100))
    parallel = list(random_games([1.0, "2.00", 3], 5, 99, 42, max_turns=100))
    assert parallel == serial
    assert [r["n"] for r in serial] == [1] * 5 + [2] * 5 + [3] * 5
    assert [r["game_index"] for r in serial] == list(range(15))
    assert [r["seed"] for r in serial] == list(range(42, 57))
    assert serial[:5] == list(random_games(1, 5, 1, 42, max_turns=100))
    assert serial[6]["state"] == list(random_games(2, 1, 1, 48, max_turns=100))[0]["state"]
    for row in serial:
        disks = [d for pole in row["state"]["poles"].values() for d in pole]
        disks += [d for d in row["state"]["hands"].values() if d]
        assert sorted(disks) == list(range(1, 2 * row["n"] + 1))
        assert row["illegal_actions"] == 0


def test_task_submission_cpu_cap_and_individual_budgets(monkeypatch):
    calls = []

    def capture(function, tasks, workers):
        calls.append(workers)
        return map(function, tasks)

    monkeypatch.setattr("app.runner.os.process_cpu_count", lambda: 2)
    monkeypatch.setattr("app.runner.bounded_map", capture)
    rows = list(random_games((1, 2, 10), 2, 99, 7, Settings(moves_factor=1, max_moves=4)))
    assert calls == [2]
    assert [r["n"] for r in rows] == [1, 1, 2, 2, 10, 10]
    assert [r["seed"] for r in rows] == list(range(7, 13))
    assert [r["turns_processed"] for r in rows] == [1, 1, 3, 3, 4, 4]


@pytest.mark.parametrize("sizes,override", [
    ([], None), ([1, 11], None), ([1, 2.5], None), ([1, "2.5"], None),
    ([1, True], None), ([1, 0], None), ([1, -2], None), ([2, 1], 1001),
])
def test_validate_all_sizes_before_scheduling(sizes, override, monkeypatch):
    def forbid_work(*args, **kwargs):
        raise AssertionError("must validate every N and budget before creating work")

    monkeypatch.setattr("app.runner.bounded_map", forbid_work)
    with pytest.raises(ValueError):
        list(random_games(sizes, 1, 2, 42, max_turns=override))


def test_cli_multi_n_summary_and_duplicate_sizes():
    output = cli("random-play", "1.0", "2.00", "1", "--games", "2", "--workers", "99",
                 "--seed", "42", "--max-turns", "1")
    assert output.returncode == 0, output.stderr
    *games, summary = [json.loads(line) for line in output.stdout.splitlines()]
    assert [r["n"] for r in games] == [1, 1, 2, 2, 1, 1]
    assert summary["games"] == summary["move_limit"] == 6
    assert summary["base_seed"] == 42 and summary["type"] == "summary"
    assert all(r["type"] == "game" for r in games)
    assert summary["wins"] == {"A": 0, "B": 0}
    assert summary["by_n"] == {
        "1": {"games": 4, "wins": {"A": 0, "B": 0}, "move_limit": 4},
        "2": {"games": 2, "wins": {"A": 0, "B": 0}, "move_limit": 2},
    }


def test_cli_multi_n_wins_summary():
    output = cli("random-play", "1", "3", "--games", "5", "--seed", "42")
    assert output.returncode == 0, output.stderr
    *games, summary = [json.loads(line) for line in output.stdout.splitlines()]
    assert len(games) == summary["games"] == 10
    for key, group in summary["by_n"].items():
        rows = [r for r in games if r["n"] == int(key)]
        assert group["games"] == len(rows) == 5
        assert group["wins"] == {p: sum(r["winner"] == p for r in rows) for p in ("A", "B")}
        assert group["move_limit"] == sum(r["stop_reason"] == "move_limit" for r in rows)
    assert summary["wins"] == {p: sum(r["winner"] == p for r in games) for p in ("A", "B")}


@pytest.mark.parametrize("args", [("1", "11"), ("1", "2.5"),
                                 ("1.5",), ("11",), ("1", "--workers", "0"),
                                 ("1", "--max-turns", "1001"),
                                 ("2", "1", "--max-turns", "1001")])
def test_cli_invalid_options_emit_no_partial_results(args):
    output = cli("random-play", *args)
    assert output.returncode == 2 and not output.stdout
    assert "error:" in output.stderr and "Traceback" not in output.stderr
