"""JSON random requests and mixed jobs sharing one bounded process pool."""
import secrets

from .config import Settings
from .engine import positive_int
from .runner import bounded_map, random_game, random_tasks, replay, replay_file, worker_count


def random_request(data):
    if (not isinstance(data, dict) or "n" not in data
            or set(data) - {"n", "games", "seed", "max_turns"}):
        raise ValueError("random input requires n; optional fields: games, seed, max_turns")
    seed = data.get("seed", secrets.randbits(64))
    if type(seed) is not int:
        raise ValueError("seed must be an integer")
    n = data["n"] if isinstance(data["n"], list) else [data["n"]]
    return n, positive_int(data.get("games", 1), "games"), seed, data.get("max_turns")


def mixed_job(task):
    index, job_index, mode, payload, settings, limit = task
    identity = {"game_index": index, "job_index": job_index, "mode": mode}
    try:
        if mode == "error":
            raise ValueError(payload)
        if mode == "random-play":
            outcome = random_game(payload)
        elif "file" in payload:
            outcome = replay_file((index, payload["file"], settings, limit))
        else:
            outcome = replay(payload["recording"], settings, limit)
        return {"type": "game", **outcome, **identity}
    except (ValueError, OSError, RecursionError) as exc:
        return {"type": "error", **identity, "error": str(exc)}


def mixed_games(data, workers=None, settings=Settings()):
    if (not isinstance(data, dict) or set(data) != {"jobs"}
            or not isinstance(data["jobs"], list) or not data["jobs"]):
        raise ValueError("batch requires a nonempty jobs list")
    plans = []
    for index, job in enumerate(data["jobs"]):
        mode, limit = "error", None
        try:
            if not isinstance(job, dict):
                raise ValueError("each job must be an object with a mode")
            mode = job.get("mode")
            if mode == "random-play":
                n, games, seed, limit = random_request({k: v for k, v in job.items() if k != "mode"})
                count, tasks = random_tasks(n, games, seed, settings, limit)
            elif mode == "replay":
                if (len(set(job) & {"recording", "file"}) != 1
                        or set(job) - {"mode", "recording", "file", "max_turns"}):
                    raise ValueError("replay job requires exactly one of recording or file")
                if "file" in job and (not isinstance(job["file"], str) or job["file"] in ("", "-")):
                    raise ValueError("replay file must be a nonempty path, not stdin")
                limit = job.get("max_turns")
                count, tasks = 1, iter((job,))
            else:
                raise ValueError("job mode must be replay or random-play")
        except ValueError as exc:
            mode, count, tasks = "error", 1, iter((str(exc),))
        plans.append((index, mode, limit, count, tasks))
    total = sum(plan[3] for plan in plans)
    tasks = ((job, mode, payload, settings, limit)
             for job, mode, limit, _, items in plans for payload in items)
    yield from bounded_map(mixed_job, ((i, *task) for i, task in enumerate(tasks)),
                           worker_count(total, workers))
