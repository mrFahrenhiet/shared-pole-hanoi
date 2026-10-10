import json

import pytest

from app.batch import mixed_games
from app.runner import random_games
from test_runner import cli, recording


def test_random_json_file_and_stdin_match_cli(tmp_path):
    request = {"n": [1.0, "3.00"], "games": 2, "seed": -42, "max_turns": 30}
    path = tmp_path / "random.json"
    path.write_text(json.dumps(request))
    expected = list(random_games([1, 3], 2, 1, -42, max_turns=30))
    for source in (str(path), "-"):
        output = cli("random-play", "--input", source, "--workers", "2", input=path.read_text())
        assert output.returncode == 0, output.stderr
        *games, summary = [json.loads(line) for line in output.stdout.splitlines()]
        assert games == [{"type": "game", **row} for row in expected]
        assert summary["games"] == 4 and summary["base_seed"] == -42


@pytest.mark.parametrize("data", [[], {}, {"n": []}, {"n": [1, 11]}, {"n": True},
    {"n": 1, "games": None}, {"n": 1, "games": 0}, {"n": 1, "seed": True},
    {"n": 1, "seed": 1.5}, {"n": 1, "seed": "42"}, {"n": 1, "extra": 2},
    {"n": [2, 1], "max_turns": 1001}])
def test_random_json_invalid_request_no_partial_output(data):
    output = cli("random-play", "--input", "-", input=json.dumps(data))
    assert output.returncode == 2 and not output.stdout and "Traceback" not in output.stderr


@pytest.mark.parametrize("args", [("1",), ("--games", "2"), ("--seed", "42"),
                                 ("--max-turns", "2"), ("--workers", "0")])
def test_random_json_conflicting_or_invalid_flags_before_read(args):
    output = cli("random-play", "--input", "missing.json", *args)
    assert output.returncode == 2 and not output.stdout
    assert "No such file" not in output.stderr


def test_mixed_jobs_order_serial_parallel_and_one_pool(tmp_path, monkeypatch):
    path = tmp_path / "replay.json"
    path.write_text(json.dumps(recording()))
    data = {"jobs": [
        {"mode": "random-play", "n": [1, 3], "games": 2, "seed": 42, "max_turns": 20},
        {"mode": "replay", "recording": recording()},
        {"mode": "replay", "file": str(path)},
        {"mode": "random-play", "n": 2, "seed": 5, "max_turns": 10},
    ]}
    monkeypatch.setattr("app.runner.os.process_cpu_count", lambda: 2)
    serial = list(mixed_games(data, 1))
    assert serial == list(mixed_games(data, 99))
    assert [r["game_index"] for r in serial] == list(range(7))
    assert [r["job_index"] for r in serial] == [0, 0, 0, 0, 1, 2, 3]
    assert [r["seed"] for r in serial if r["mode"] == "random-play"] == [42, 43, 44, 45, 5]
    assert serial[4]["winner"] == serial[5]["winner"] == "A"
    calls = []

    def capture(function, tasks, workers):
        calls.append(workers)
        return map(function, tasks)

    monkeypatch.setattr("app.batch.bounded_map", capture)
    assert list(mixed_games(data, 99)) == serial and calls == [2]


@pytest.mark.parametrize("job", [None, {}, {"mode": "unknown"},
    {"mode": "random-play", "n": [1, 11]}, {"mode": "random-play", "n": 1, "seed": False},
    {"mode": "replay", "recording": {}}, {"mode": "replay", "file": "missing.json"},
    {"mode": "replay", "file": "-"}, {"mode": "replay", "file": 3},
    {"mode": "replay", "file": "x", "recording": recording()},
    {"mode": "replay", "recording": recording(), "max_turns": 1001}])
def test_mixed_bad_job_does_not_abort_other_jobs(job):
    valid = {"mode": "replay", "recording": recording()}
    rows = list(mixed_games({"jobs": [valid, job, valid]}, 1))
    assert [r["type"] for r in rows] == ["game", "error", "game"]
    assert rows[0]["winner"] == rows[2]["winner"] == "A"


@pytest.mark.parametrize("data", [None, [], {}, {"jobs": []}, {"jobs": {}},
                                     {"jobs": [{}], "extra": 1}])
def test_invalid_manifest_rejected(data):
    output = cli("batch", "-", input=json.dumps(data))
    assert output.returncode == 2 and not output.stdout


def test_mixed_cli_file_stdin_summary_and_errors(tmp_path):
    data = {"jobs": [{"mode": "random-play", "n": [1, 2], "seed": 7, "max_turns": 1},
                     {"mode": "replay", "recording": recording()}, {"mode": "bad"}]}
    path = tmp_path / "batch.json"
    path.write_text(json.dumps(data))
    for source in (str(path), "-"):
        output = cli("batch", source, "--workers", "2", input=path.read_text())
        *games, summary = [json.loads(line) for line in output.stdout.splitlines()]
        assert output.returncode == 1 and "Traceback" not in output.stderr
        assert [r["type"] for r in games] == ["game", "game", "game", "error"]
        assert summary == {"type": "summary", "games": 4, "succeeded": 3, "failed": 1,
                           "wins": {"A": 1, "B": 0},
                           "stop_reasons": {"win": 1, "move_limit": 2, "input_exhausted": 0}}
    assert cli("batch", "-", input=json.dumps({"jobs": data["jobs"][:-1]})).returncode == 0


def test_random_json_scalar_defaults_and_generated_seed():
    output = cli("random-play", "--input", "-", input='{"n":"3.00","max_turns":1}')
    game, summary = [json.loads(line) for line in output.stdout.splitlines()]
    assert output.returncode == 0 and game["n"] == 3 and summary["games"] == 1
    assert type(game["seed"]) is int and summary["base_seed"] == game["seed"]
