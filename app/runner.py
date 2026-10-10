"""Execution budgets, replay validation, and independent random games."""
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass
import json
import multiprocessing
import os
from pathlib import Path
import random

from .engine import legal_actions, new_game, observe, positive_int, snapshot, step
from .schemas import Action


@dataclass(frozen=True, slots=True)
class Settings:
    max_n: int = 10
    moves_factor: int = 1000
    max_moves: int = 100000

    @classmethod
    def from_env(cls):
        return cls(*(positive_int(os.environ.get(name, default), name)
                     for name, default in (("HANOI_MAX_N", 10),
                                           ("HANOI_MOVES_FACTOR", 1000),
                                           ("HANOI_MAX_MOVES", 100000))))

    def budget(self, n, override=None):
        n = positive_int(n, "N")
        if n > self.max_n:
            raise ValueError(f"N must not exceed {self.max_n}")
        # Avoid constructing enormous integers for unusually large configured N.
        cap = self.max_moves
        limit = cap if n >= cap.bit_length() else min(cap, self.moves_factor * (2**n - 1))
        if override is not None:
            override = positive_int(override, "max-turns")
            if override > limit:
                raise ValueError(f"max-turns must not exceed the N-derived limit {limit}")
            limit = override
        return limit


def result(state, won, turns, illegal, limit, **extra):
    return {"state": snapshot(state), "winner": won, "turns_processed": turns,
            "illegal_actions": illegal,
            "stop_reason": "win" if won else "move_limit" if turns >= limit else "input_exhausted",
            **extra}


def replay(data, settings=Settings(), max_turns=None):
    if not isinstance(data, dict) or set(data) != {"n", "turn_order", "moves"}:
        raise ValueError("replay requires exactly n, turn_order, and moves")
    order, moves = data["turn_order"], data["moves"]
    if not isinstance(order, list) or not isinstance(moves, list) or len(order) != len(moves):
        raise ValueError("turn_order and moves must be equally sized lists")
    if any(player not in ("A", "B") for player in order):
        raise ValueError("turn_order players must be A or B")
    actions = []
    for move in moves:
        if (not isinstance(move, dict) or "kind" not in move
                or set(move) - {"kind", "pole"} or not isinstance(move["kind"], str)):
            raise ValueError("each move requires a string kind and optional string pole")
        if "pole" in move and not isinstance(move["pole"], str):
            raise ValueError("pole must be a string")
        if move["kind"] in ("lift", "place") and "pole" not in move:
            raise ValueError("lift and place require pole")
        if move["kind"] == "skip" and "pole" in move:
            raise ValueError("skip takes no pole")
        actions.append(Action(**move))
    state = new_game(data["n"], max_n=settings.max_n)
    limit = settings.budget(data["n"], max_turns)
    turns = illegal = 0
    won = None
    for player, action in zip(order, actions):
        if turns >= limit:
            break
        outcome = step(state, player, action)
        state, won = outcome.state, outcome.winner
        turns += 1
        illegal += not outcome.legal
        if won:
            break
    return result(state, won, turns, illegal, limit, unused_moves=len(moves) - turns)


def worker_count(games, requested=None):
    games = positive_int(games, "games")
    workers = (os.process_cpu_count() or 1) if requested is None else positive_int(requested, "workers")
    return min(games, workers)


def bounded_map(function, tasks, workers, chunksize):
    if workers == 1:
        yield from map(function, tasks)
    else:
        with ProcessPoolExecutor(workers, mp_context=multiprocessing.get_context("spawn")) as pool:
            yield from pool.map(function, tasks, chunksize=chunksize, buffersize=workers * 2)


def replay_file(task):
    index, source, settings, max_turns = task
    identity = {"game_index": index, "source": str(source)}
    try:
        data = json.loads(Path(source).read_text())
        return {"type": "game", **identity, **replay(data, settings, max_turns)}
    except (ValueError, OSError) as exc:
        return {"type": "error", **identity, "error": str(exc)}


def replay_games(paths, workers=None, settings=Settings(), max_turns=None):
    workers = worker_count(len(paths), workers)
    if any(str(path) == "-" for path in paths):
        raise ValueError("stdin (-) is supported only as the sole replay input")
    if max_turns is not None:
        max_turns = positive_int(max_turns, "max-turns")
    tasks = ((i, path, settings, max_turns) for i, path in enumerate(paths))
    yield from bounded_map(replay_file, tasks, workers, chunksize=1)


def next_player(counts, rng):
    if counts[0] == counts[1]:
        return rng.choice(("A", "B"))
    return "A" if counts[0] < counts[1] else "B"


def random_action(view, actions, rng):
    """Agent boundary: only a restricted view and its actions are supplied."""
    return rng.choice(actions)


def random_game(task):
    index, n, seed, limit, max_n = task
    rng = random.Random(seed)
    state = new_game(n, max_n=max_n)
    counts = [0, 0]
    won = None
    for turns in range(1, limit + 1):
        player = next_player(counts, rng)
        view = observe(state, player)
        action = random_action(view, legal_actions(view), rng)
        outcome = step(state, player, action)
        state, won = outcome.state, outcome.winner
        counts[player == "B"] += 1
        if won:
            break
    return result(state, won, turns, 0, limit, game_index=index, seed=seed)


def random_games(n, games, workers, seed, settings=Settings(), max_turns=None):
    limit = settings.budget(n, max_turns)
    n = positive_int(n, "N")
    games = positive_int(games, "games")
    workers = worker_count(games, workers)
    tasks = ((i, n, seed + i, limit, settings.max_n) for i in range(games))
    yield from bounded_map(random_game, tasks, workers, chunksize=8)
