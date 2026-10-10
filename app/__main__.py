"""Replay and random-play command line frontends."""
import argparse
import json
from pathlib import Path
import secrets
import sys
import time

from .config import Settings
from .batch import mixed_games, random_request
from .engine import positive_int
from .runner import random_games, replay, replay_games, worker_count


def print_batch(outcomes):
    wins = {"A": 0, "B": 0}
    stops = {"win": 0, "move_limit": 0, "input_exhausted": 0}
    failed = total = 0
    for outcome in outcomes:
        total += 1
        print(json.dumps(outcome), flush=True)
        if outcome["type"] == "error":
            failed += 1
        else:
            stops[outcome["stop_reason"]] += 1
            if outcome["winner"]:
                wins[outcome["winner"]] += 1
    print(json.dumps({"type": "summary", "games": total,
                      "succeeded": total - failed, "failed": failed,
                      "wins": wins, "stop_reasons": stops}))
    return int(failed > 0)


def read_json(source):
    return json.loads(sys.stdin.read() if source == "-" else Path(source).read_text())


def main():
    parser = argparse.ArgumentParser(prog="shared-pole-hanoi", description=__doc__)
    modes = parser.add_subparsers(dest="mode", required=True)
    recorded = modes.add_parser("replay", help="run JSON recordings; use - alone for stdin")
    recorded.add_argument("files", nargs="+")
    random = modes.add_parser("random-play", help="run random valid agents")
    random.add_argument("n", nargs="*", help="one or more disk counts")
    random.add_argument("--input", help="JSON random request; - for stdin")
    random.add_argument("--games", help="games per supplied N (default: 1)")
    random.add_argument("--seed", type=int)
    for mode in (recorded, random):
        mode.add_argument("--workers")
        mode.add_argument("--max-turns")
    batch = modes.add_parser("batch", help="run mixed random/replay jobs from JSON")
    batch.add_argument("input", help="JSON manifest; - for stdin")
    batch.add_argument("--workers")
    args = parser.parse_args()
    try:
        settings = Settings.from_env()
        if args.mode == "batch":
            worker_count(1, args.workers)
            return print_batch(mixed_games(read_json(args.input), args.workers, settings))
        if args.max_turns is not None:
            args.max_turns = positive_int(args.max_turns, "max-turns")
        if args.mode == "replay":
            workers = worker_count(len(args.files), args.workers)
            if "-" in args.files and len(args.files) != 1:
                raise ValueError("stdin (-) is supported only as the sole replay input")
            if len(args.files) > 1:
                return print_batch(replay_games(args.files, workers, settings, args.max_turns))
            print(json.dumps(replay(read_json(args.files[0]), settings, args.max_turns)))
            return
        if args.input:
            if args.n or any(v is not None for v in (args.games, args.seed, args.max_turns)):
                raise ValueError("--input cannot be combined with N, --games, --seed, or --max-turns")
            worker_count(1, args.workers)
            args.n, args.games, args.seed, args.max_turns = random_request(read_json(args.input))
        games = positive_int(args.games if args.games is not None else 1, "games")
        total = games * len(args.n)
        seed = args.seed if args.seed is not None else secrets.randbits(64)
        wins = {"A": 0, "B": 0}
        limited = 0
        by_n = {}
        started = time.perf_counter()
        for outcome in random_games(args.n, games, args.workers, seed, settings, args.max_turns):
            print(json.dumps({"type": "game", **outcome}), flush=True)
            group = by_n.setdefault(str(outcome["n"]),
                                    {"games": 0, "wins": {"A": 0, "B": 0}, "move_limit": 0})
            group["games"] += 1
            if outcome["winner"]:
                wins[outcome["winner"]] += 1
                group["wins"][outcome["winner"]] += 1
            else:
                limited += 1
                group["move_limit"] += 1
        elapsed = time.perf_counter() - started
        print(json.dumps({"type": "summary", "games": total, "base_seed": seed,
                          "wins": wins, "move_limit": limited, "elapsed_seconds": elapsed,
                          "games_per_second": total / elapsed, "by_n": by_n}))
    except (ValueError, OSError, RecursionError) as exc:
        parser.error(str(exc))


if __name__ == "__main__":
    sys.exit(main())
