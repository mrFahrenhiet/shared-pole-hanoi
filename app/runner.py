"""Replay validation and independent game execution."""
from concurrent.futures import ProcessPoolExecutor
import json
import multiprocessing
import os
from pathlib import Path
import random

from .config import Settings
from .engine import legal_actions, new_game, observe, positive_int, snapshot, step
from .schemas import Action


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
    state = new_game(data["n"], max_n=settings.max_n)
    limit = settings.budget(data["n"], max_turns)
    turns = illegal = 0
    won = None
    for player, move in zip(order, moves):
        if turns >= limit:
            break
        outcome = step(state, player, Action(**move))
        state, won = outcome.state, outcome.winner
        turns += 1
        illegal += not outcome.legal
        if won:
            break
    return result(state, won, turns, illegal, limit, unused_moves=len(moves) - turns)


def worker_count(games, requested=None):
    games = positive_int(games, "games")
    cpus = os.process_cpu_count() or 1
    workers = cpus if requested is None else positive_int(requested, "workers")
    return min(games, workers, cpus)


def bounded_map(function, tasks, workers):
    if workers == 1:
        yield from map(function, tasks)
    else:
        with ProcessPoolExecutor(workers, mp_context=multiprocessing.get_context("spawn")) as pool:
            yield from pool.map(function, tasks, chunksize=1, buffersize=workers * 2)


def replay_file(task):
    index, source, settings, max_turns = task
    identity = {"game_index": index, "source": str(source)}
    try:
        data = json.loads(Path(source).read_text())
        return {"type": "game", **identity, **replay(data, settings, max_turns)}
    except (ValueError, OSError, RecursionError) as exc:
        return {"type": "error", **identity, "error": str(exc)}


def replay_games(paths, workers=None, settings=Settings(), max_turns=None):
    workers = worker_count(len(paths), workers)
    if any(str(path) == "-" for path in paths):
        raise ValueError("stdin (-) is supported only as the sole replay input")
    if max_turns is not None:
        max_turns = positive_int(max_turns, "max-turns")
    tasks = ((i, path, settings, max_turns) for i, path in enumerate(paths))
    yield from bounded_map(replay_file, tasks, workers)


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
    illegal = 0
    won = None
    for turns in range(1, limit + 1):
        player = next_player(counts, rng)
        view = observe(state, player)
        action = random_action(view, legal_actions(view), rng)
        outcome = step(state, player, action)
        illegal += not outcome.legal
        state, won = outcome.state, outcome.winner
        counts[player == "B"] += 1
        if won:
            break
    return result(state, won, turns, illegal, limit, game_index=index, seed=seed, n=n)


def random_tasks(n, games, seed, settings=Settings(), max_turns=None):
    values = n if isinstance(n, (list, tuple)) else [n]
    if not values:
        raise ValueError("at least one N is required")
    sizes = [positive_int(value, "N") for value in values]
    limits = [settings.budget(size, max_turns) for size in sizes]
    games = positive_int(games, "games")
    tasks = ((batch * games + i, size, seed + batch * games + i, limit, settings.max_n)
             for batch, (size, limit) in enumerate(zip(sizes, limits)) for i in range(games))
    return games * len(sizes), tasks


def random_games(n, games, workers, seed, settings=Settings(), max_turns=None):
    total, tasks = random_tasks(n, games, seed, settings, max_turns)
    yield from bounded_map(random_game, tasks, worker_count(total, workers))
