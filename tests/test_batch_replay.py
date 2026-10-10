import json
from pathlib import Path
import sys

import pytest

from hanoi.__main__ import main
from hanoi.runner import Settings, replay, replay_games, worker_count
from test_runner import cli, recording


def save(directory, name, data):
    path = directory / name
    path.write_text(json.dumps(data))
    return str(path)


def test_batch_order_isolation_and_serial_parallel_equality(tmp_path):
    win = save(tmp_path, "win.json", recording())
    illegal = save(tmp_path, "illegal.json", {
        "n": 1, "turn_order": ["B"], "moves": [{"kind": "lift", "pole": "1a"}]})
    bad_json = tmp_path / "bad.json"
    bad_json.write_text("not json")
    bad_schema = save(tmp_path, "schema.json", {})
    missing = str(tmp_path / "missing.json")
    paths = [win, missing, str(bad_json), bad_schema, illegal, win]
    serial = list(replay_games(paths, workers=1))
    parallel = list(replay_games(paths, workers=3))
    assert parallel == serial
    assert [r["game_index"] for r in serial] == list(range(6))
    assert [r["source"] for r in serial] == paths
    assert [r["type"] for r in serial] == ["game", "error", "error", "error", "game", "game"]
    assert serial[0]["winner"] == serial[-1]["winner"] == "A"
    assert serial[4]["illegal_actions"] == 1
    assert serial[4]["state"]["poles"]["1a"] == [1]


def test_workers_open_files_independently(tmp_path, monkeypatch):
    paths = [save(tmp_path, f"{i}.json", recording()) for i in range(2)]

    def forbid_parent_reads(*args, **kwargs):
        raise AssertionError("parent must not load replay files")

    monkeypatch.setattr(Path, "read_text", forbid_parent_reads)
    assert all(r["type"] == "game" for r in replay_games(paths, workers=2))


def test_cli_batch_errors_continue_and_exit_nonzero(tmp_path):
    good = save(tmp_path, "good.json", recording())
    missing = str(tmp_path / "missing.json")
    output = cli("replay", good, missing, good, "--workers", "2")
    assert output.returncode == 1 and "Traceback" not in output.stderr
    records = [json.loads(line) for line in output.stdout.splitlines()]
    assert [r["type"] for r in records] == ["game", "error", "game", "summary"]
    assert records[-1] == {"type": "summary", "games": 3, "succeeded": 2, "failed": 1,
                           "wins": {"A": 2, "B": 0},
                           "stop_reasons": {"win": 2, "move_limit": 0, "input_exhausted": 0}}
    success = cli("replay", good, good, "--workers", "2")
    assert success.returncode == 0


def test_batch_per_n_budget_failures_and_environment(tmp_path, monkeypatch):
    n1 = save(tmp_path, "n1.json", recording())
    n2 = save(tmp_path, "n2.json", {"n": 2, "turn_order": ["A"], "moves": [{"kind": "skip"}]})
    results = list(replay_games([n1, n2], 2, max_turns=1500))
    assert results[0]["type"] == "error" and "1000" in results[0]["error"]
    assert results[1]["stop_reason"] == "input_exhausted"
    monkeypatch.setenv("HANOI_MOVES_FACTOR", "2")
    monkeypatch.setenv("HANOI_MAX_MOVES", "10")
    output = cli("replay", n1, n2, "--workers", "2", "--max-turns", "3")
    assert output.returncode == 1
    records = [json.loads(line) for line in output.stdout.splitlines()]
    assert records[0]["type"] == "error" and "limit 2" in records[0]["error"]
    assert records[1]["type"] == "game"
    limited = list(replay_games([n1, n1], 2, Settings(max_moves=1)))
    assert all(r["stop_reason"] == "move_limit" and r["turns_processed"] == 1 for r in limited)


def test_single_file_and_stdin_compatibility(tmp_path):
    path = save(tmp_path, "single.json", recording())
    expected = replay(recording())
    for output in (cli("replay", path, "--workers", "4"),
                   cli("replay", "-", "--workers", "2", input=json.dumps(recording()))):
        assert output.returncode == 0
        assert len(output.stdout.splitlines()) == 1
        assert json.loads(output.stdout) == expected


@pytest.mark.parametrize("args", [
    ["-", "file.json"], ["-", "-"], ["-", "--workers", "0"],
    ["file.json", "--workers", "1.0"], ["-", "--max-turns", "0"],
    ["file.json", "other.json", "--max-turns", "-1"],
])
def test_invalid_global_options_fail_before_reading(args, monkeypatch, capsys):
    def forbid_reads(*args, **kwargs):
        raise AssertionError("input must not be read before validation")

    monkeypatch.setattr(Path, "read_text", forbid_reads)
    monkeypatch.setattr(sys.stdin, "read", forbid_reads)
    monkeypatch.setattr(sys, "argv", ["hanoi", "replay", *args])
    with pytest.raises(SystemExit) as exc:
        main()
    assert exc.value.code == 2
    assert capsys.readouterr().out == ""


def test_default_and_explicit_worker_counts(monkeypatch):
    monkeypatch.setattr("hanoi.runner.os.process_cpu_count", lambda: 4)
    assert worker_count(2) == 2
    assert worker_count(8) == 4
    assert worker_count(2, "99") == 2
    monkeypatch.setattr("hanoi.runner.os.process_cpu_count", lambda: None)
    assert worker_count(2) == 1
    with pytest.raises(ValueError):
        worker_count(1, 0)
