# Shared-pole Hanoi

A Python 3.14 engine with replay and random-play command line frontends. All
Python execution, dependency management, and tests run inside Docker using uv.
The engine uses immutable fixed dataclasses and has no global game state. Pole
stacks are tuples ordered bottom to top; hands contain a disk size or `0`.

## Run in Docker

From this directory:

```sh
docker compose build
docker compose run --rm test
docker compose run --rm app replay /data/example.json
docker compose run --rm app replay /data/example.json /data/b_wins.json --workers 2
docker compose run --rm app random-play 3
docker compose run --rm app random-play 3 --games 10000 --workers 4 --seed 42 --max-turns 1000
```

`app` targets the production stage of the multi-stage Dockerfile; `test` adds
pytest and Hypothesis. Both Python and uv are pinned by image digest, and
`uv.lock` fixes dependency versions. Rebuild after editing source. Examples are
mounted read-only at `/data`. Runtime has no test dependencies or test files.

To regenerate the lockfile entirely in a bootstrap container:

```sh
docker build --target base -t neom-hanoi-bootstrap .
docker run --rm --mount type=bind,source="$PWD",target=/app neom-hanoi-bootstrap uv lock
docker compose build
```

## Inputs, limits, and results

`N` accepts positive integers and strings containing decimal digits, with
optional surrounding whitespace. Floats, booleans, decimal strings such as
`"3.0"`, and scientific notation are rejected. The default maximum is **10**.

Set these variables in the environment or a Compose `.env` file. The sample
`.env.example` contains defaults. Every setting must be a positive integer.

| Variable | Default | Meaning |
| --- | ---: | --- |
| `HANOI_MAX_N` | 10 | Maximum disks per player |
| `HANOI_MOVES_FACTOR` | 1000 | Budget multiplier |
| `HANOI_MAX_MOVES` | 100000 | Absolute action cap per game |

The action budget for either frontend is
`min(HANOI_MAX_MOVES, HANOI_MOVES_FACTOR * (2**N - 1))`. This is a resource
budget, not a guarantee that a random game ends. `--max-turns` can lower, but
cannot raise, that budget. Every skip and illegal action consumes a turn.
Reaching the limit reports `move_limit` with no winner, not a rules-based draw.
A win on the final permitted turn takes precedence over the limit.

Replay accepts a JSON file or `-` for stdin:

```json
{
  "n": "1",
  "turn_order": ["A", "B", "A"],
  "moves": [
    {"kind": "lift", "pole": "1a"},
    {"kind": "lift", "pole": "1b"},
    {"kind": "place", "pole": "3a"}
  ]
}
```

The top-level fields must be exactly `n`, `turn_order`, and `moves`, and both
lists must have equal lengths. Players are `A` or `B`. Each move has a string
`kind`, plus a string `pole` for lift/place. Skip is `{"kind": "skip"}`.
Unknown fields, missing required fields, bad structural types, and unknown
players are input errors with nonzero exit status. Unknown action or pole
strings are illegal gameplay actions: the turn is consumed without mutation.
B targeting `1a` or `3a` is likewise illegal. The engine enforces this even when
the JSON is structurally valid. The entire recording is structurally validated
before execution, including entries that follow an early win.

Replay accepts arbitrary turn sequences, including `A, A`. It outputs one JSON
object with `state`, `winner`, `turns_processed`, `illegal_actions`, `stop_reason`,
and `unused_moves`. It stops at a win, the budget, or input exhaustion.

Pass multiple paths to replay independent recordings concurrently. `--workers`
defaults to the smaller of input count and available CPUs; `--workers 1` runs
sequentially. Each worker opens and validates its own file, with one input per
task and bounded queued work. Results stream in input order as JSON Lines:
successful records have `type: "game"`, `game_index`, `source`, and the existing
replay result. File, JSON, or schema failures produce `type: "error"` with
`game_index`, `source`, and `error`; other inputs continue. The final summary
reports `games`, `succeeded`, `failed`, `wins`, and `stop_reasons`. Any failed
input gives exit status 1. Illegal gameplay remains a successful replay with
counted wasted turns. A per-input N-derived budget violation is an input failure.

Single-file replay retains its original one-object output and error handling.
Stdin (`-`) must be the sole input; mixing it with paths or another `-` is rejected
before reading. Invalid global worker/max-turn values fail before reading any
input. Both frontends accept `--workers`, including a single replay file.

Random-play requires only `N`. Optional flags are `--games`, `--workers`,
`--seed`, and `--max-turns`. At equal turn counts the scheduler randomly chooses
the player; otherwise it picks the player with fewer turns. Counts always
differ by at most one, while sequences such as `A, B, B, A` are possible. The
agent uniformly chooses among legal actions, including skip, using only its
restricted view and legal action list.

Each game has its own generator seeded with `base_seed + game_index`. An
omitted seed is generated and reported. The default game count is one; default
workers are the smaller of game count and available CPUs. Multiple games use a
spawn-based `ProcessPoolExecutor` with bounded queued work and small chunks.
Results stream in game-index order as JSON Lines, followed by a summary with
win counts, limit counts, seed, elapsed seconds, and games per second. Results
are reproducible across worker counts; timing fields naturally differ. No
complete histories or collection of all results is retained. Ordered output
can wait behind an earlier slow game, with buffering bounded by worker count.

## Engine API and views

Import these from `hanoi`:

```python
new_game(n, *, max_n=10)       # GameState
observe(state, player)        # PlayerView
legal_actions(view)           # tuple[Action, ...]
step(state, player, action)   # StepResult
snapshot(state)               # detached JSON-compatible full-board dict
```

`Poles`, `Hands`, `GameState`, `Action`, `PlayerView`, and `StepResult` are
frozen, slotted dataclasses. State transitions return new states. Player views
contain only the player's identity, three visible stacks, and hand; they have
no reference to the full state. `snapshot` is for trusted replay/debugging
callers and exposes both players. This is a visibility boundary, not an admin
authentication system. Keep full states and snapshots away from agents.

All game dataclasses and the `Player` type alias live in `hanoi/schemas.py`.
`engine.py` contains rules, `runner.py` contains execution/configuration, and
`__main__.py` contains the CLI. Public imports such as `from hanoi import Action`
remain available.

`StepResult` has `state`, `legal`, `reason`, and `winner`. Illegal actions return
the exact unchanged state with reason `illegal_action`. Bad player identifiers
raise `ValueError`. The engine accepts any supplied player order and does not
read environment settings. Runners own limits, counts, and scheduling.

The engine checks both players after a move. To win, a player's hand, private
pole 1, and shared pole 2 must be empty, and their pole 3 must be nonempty.
Disk ownership is irrelevant. Clearing shared pole 2 can let the other player
win. The first winning state ends the game; subsequent calls return
`game_over` without changing it. Opponent private disks or a held disk do not
block victory. From legal play, both players cannot first win on the same
action: clearing the shared pole puts its last disk into the actor's hand.

Construct states with `new_game`, then use `step`. Direct dataclass construction
is available for tests but assumes the caller supplies valid stacks and unique
positive disks; Python type annotations do not validate arbitrary objects.
For a future service, store each game's state separately and serialize updates
to that game with a lock or version check. Independent games share no mutable
state. No web server, persistence, or authorization layer is included.

## Verification

Tests exercise engine transitions directly, visibility, illegal moves, unusual
win states, numeric input validation, replay schemas, budget precedence,
balanced scheduling, and serial/parallel reproducibility. Hypothesis generates
action sequences to check conservation and stack order. CLI integration tests
verify JSON output and environment wiring. Batch replay tests check ordering,
worker-local file reads, independent failures, budgets, and compatibility with
single-file/stdin replay.

The application source is kept below 500 physical Python lines (tests excluded).
To count it inside the runtime container:

```sh
docker compose run --rm --entrypoint uv app run --locked --no-sync python -c \
  'from pathlib import Path; print(sum(len(p.read_text().splitlines()) for p in Path("hanoi").glob("*.py")))'
```

The standard library handles data models, parsing, JSON, randomness, and
parallelism; pytest and Hypothesis provide testing rather than custom test
frameworks. The small custom part is the game's rule set and execution policy.

Verified in the Docker environment on 2026-10-11 using Python 3.14.8 and uv
0.13.0: **60 tests passed**, application source **363 lines**, and the runtime
image contained neither pytest/Hypothesis nor test files. The documented
10,000-game command (N=3, four workers, seed 42, 1,000-turn cap) completed in
**8.82 seconds**, approximately **1,134 games/second**: A won 5,706, B won 4,267,
and 27 reached the limit. Throughput depends on hardware and workload. A
separate reviewer audit checked every action from all reachable N=1 and N=2
states against an independent rules implementation (109,536 action checks).
