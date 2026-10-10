"""Replay and random-play command line frontends."""
import argparse
import json
from pathlib import Path
import secrets
import sys
import time

from .engine import positive_int
from .runner import Settings, random_games, replay, replay_games, worker_count


def run_replays(paths, workers, settings, max_turns):
    wins = {"A": 0, "B": 0}
    stops = {"win": 0, "move_limit": 0, "input_exhausted": 0}
    failed = 0
    for outcome in replay_games(paths, workers, settings, max_turns):
        print(json.dumps(outcome), flush=True)
        if outcome["type"] == "error":
            failed += 1
        else:
            stops[outcome["stop_reason"]] += 1
            if outcome["winner"]:
                wins[outcome["winner"]] += 1
    print(json.dumps({"type": "summary", "games": len(paths),
                      "succeeded": len(paths) - failed, "failed": failed,
                      "wins": wins, "stop_reasons": stops}))
    return int(failed > 0)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    modes = parser.add_subparsers(dest="mode", required=True)
    recorded = modes.add_parser("replay", help="run JSON recordings; use - alone for stdin")
    recorded.add_argument("files", nargs="+")
    recorded.add_argument("--workers")
    recorded.add_argument("--max-turns")
    random = modes.add_parser("random-play", help="run random valid agents")
    random.add_argument("n")
    random.add_argument("--games", default="1")
    random.add_argument("--workers")
    random.add_argument("--seed", type=int)
    random.add_argument("--max-turns")
    args = parser.parse_args()
    try:
        settings = Settings.from_env()
        if args.max_turns is not None:
            args.max_turns = positive_int(args.max_turns, "max-turns")
        if args.mode == "replay":
            workers = worker_count(len(args.files), args.workers)
            if "-" in args.files and len(args.files) != 1:
                raise ValueError("stdin (-) is supported only as the sole replay input")
            if len(args.files) > 1:
                return run_replays(args.files, workers, settings, args.max_turns)
            source = sys.stdin.read() if args.files[0] == "-" else Path(args.files[0]).read_text()
            print(json.dumps(replay(json.loads(source), settings, args.max_turns)))
            return
        games = positive_int(args.games, "games")
        workers = worker_count(games, args.workers)
        seed = args.seed if args.seed is not None else secrets.randbits(64)
        wins = {"A": 0, "B": 0}
        limited = 0
        started = time.perf_counter()
        for outcome in random_games(args.n, games, workers, seed, settings, args.max_turns):
            print(json.dumps({"type": "game", **outcome}), flush=True)
            if outcome["winner"]:
                wins[outcome["winner"]] += 1
            else:
                limited += 1
        elapsed = time.perf_counter() - started
        print(json.dumps({"type": "summary", "games": games, "base_seed": seed,
                          "wins": wins, "move_limit": limited, "elapsed_seconds": elapsed,
                          "games_per_second": games / elapsed}))
    except (ValueError, OSError) as exc:
        parser.error(str(exc))


if __name__ == "__main__":
    sys.exit(main())
