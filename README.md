# shared-pole-hanoi

A Python engine for two-player Hanoi with a shared middle pole. Two game modes,
`replay` and `random-play`, use the same engine. A `batch` command combines
both modes in one concurrent run.

All Python execution, dependency management, and tests run in Docker using uv.
You need Docker with Compose; no host Python or uv installation is required.

## Quick start

Clone the repository, or enter your existing checkout:

```sh
git clone https://github.com/mrFahrenhiet/shared-pole-hanoi.git
cd shared-pole-hanoi
docker compose build app test
docker compose run --rm test
```

Run the checked-in example: six random games across N=1, 3, 5, plus one replay:

```sh
docker compose run --rm app batch /data/example.json
```

Only [examples/example.json](examples/example.json) is a published input fixture.
Other recordings and JSONL output are ignored local artifacts. Tests generate
their own high-N and edge-case recordings in temporary directories.

The `app` service runs `uv run --locked --no-sync python -m app`. Commands
below pass arguments to that entry point. The host `examples/` directory is
mounted read-only at `/data`; input paths in CLI arguments and JSON refer to
paths **inside the container**. Rebuild after editing Python source.

```sh
docker compose run --rm app --help
docker compose run --rm app replay --help
docker compose run --rm app random-play --help
docker compose run --rm app batch --help
```

## Running replay

Replay consumes a recording containing N, an explicit turn order, and one action
per turn. It accepts arbitrary orders, including consecutive turns for a player.

### JSON format

Save this as `examples/replay.local.json`:

```json
{
  "n": 1,
  "turn_order": ["A", "B", "A"],
  "moves": [
    {"kind": "lift", "pole": "1a"},
    {"kind": "lift", "pole": "1b"},
    {"kind": "place", "pole": "3a"}
  ]
}
```

Run a file, or several recordings sequentially/concurrently:

```sh
docker compose run --rm app replay /data/replay.local.json
docker compose run --rm app replay /data/replay.local.json /data/replay.local.json --workers 1
docker compose run --rm app replay /data/replay.local.json /data/replay.local.json --workers 2
```

Repeating a path runs independent copies of that recording. Use different paths
to run different recordings. `--max-turns 2` would stop this example before its
winning placement; `--max-turns 3` allows the win.

You can supply JSON directly without creating a file:

```sh
printf '%s\n' '{"n":1,"turn_order":["A","A"],"moves":[{"kind":"lift","pole":"1a"},{"kind":"place","pole":"3a"}]}' | docker compose run --rm -T app replay -
```

`-` means stdin and must be the sole replay input. `-T` disables the container
TTY when piping input. You can also redirect a local file into stdin:

```sh
docker compose run --rm -T app replay - < examples/replay.local.json
```

### Validation and output

The recording must contain exactly `n`, `turn_order`, and `moves`. Turn and
move lists must have equal lengths; players must be `A` or `B`. Lift/place
require a string `pole`; skip is exactly `{"kind":"skip"}`.

Malformed structure, missing fields, extra fields, and unknown players reject
the input. Unknown action/pole strings, accessing an opponent's private pole,
or an illegal placement are gameplay errors: they waste a turn without changing
the board. The entire recording is structurally validated before execution,
including actions after an early win or the move cap.

A single replay produces one JSON object. For the three-turn example above:

```json
{
  "state": {
    "poles": {"1a": [], "2": [], "3a": [1], "1b": [], "3b": []},
    "hands": {"A": 0, "B": 2}
  },
  "winner": "A",
  "turns_processed": 3,
  "illegal_actions": 0,
  "stop_reason": "win",
  "unused_moves": 0
}
```

Multiple files produce JSON Lines: one `type: "game"` or `type: "error"`
record per file, followed by a summary. Records include `game_index` and
`source`. One invalid/unreadable file does not stop other recordings, including
when JSON decoding raises a recursion error.

## Running random-play

Random-play runs complete games until a win or the move cap, not just one move.

### CLI arguments

```sh
# One game with three disks per player.
docker compose run --rm app random-play 3

# Five games for EACH N: 15 games total, using available CPUs.
docker compose run --rm app random-play 1 3 5 --games 5 --seed 42

# Run the same request sequentially.
docker compose run --rm app random-play 1 3 5 --games 5 --seed 42 --workers 1

# Larger bounded workload; requested workers are still capped by available CPUs.
docker compose run --rm app random-play 3 --games 10000 --workers 4 --seed 42 --max-turns 1000
```

### JSON input

The equivalent request can be saved as `examples/random.local.json`:

```json
{
  "n": [1, "3.00", 5],
  "games": 5,
  "seed": 42,
  "max_turns": 1000
}
```

`n` is required and can be a single value or a nonempty list. `games` defaults
to 1 **per N**; `seed` is an optional integer; `max_turns` is an optional
per-game cap. Unknown fields are rejected. Omitted seeds are generated and
reported in the output.

```sh
docker compose run --rm app random-play --input /data/random.local.json
docker compose run --rm app random-play --input /data/random.local.json --workers 1
printf '%s\n' '{"n":[1,3],"games":2,"seed":42,"max_turns":100}' | docker compose run --rm -T app random-play --input -
```

`--input` cannot be combined with positional N, `--games`, `--seed`, or
`--max-turns`: the JSON is the single source for game settings. `--workers`
remains a CLI-only execution setting. The plain CLI form remains supported.

All N values and their budgets are validated before any game starts. A bad
later N rejects the whole random request without partial output. Repeated N
values schedule additional games and are merged in the per-N summary.

Random-play outputs one JSONL game record per game, then a summary. Game records
include final state, winner, turn/illegal counts, stop reason, `n`,
`game_index`, and `seed`. The summary includes `games`, `base_seed`,
`wins`, `move_limit`, `by_n`, elapsed seconds, and games per second.

## Mixing random and replay games

Use a manifest with a nonempty `jobs` array. For example:

```json
{
  "jobs": [
    {"mode": "random-play", "n": [1, 3], "games": 2, "seed": 42, "max_turns": 1000},
    {
      "mode": "replay",
      "recording": {
        "n": 1,
        "turn_order": ["A", "A"],
        "moves": [
          {"kind": "lift", "pole": "1a"},
          {"kind": "place", "pole": "3a"}
        ]
      }
    },
    {"mode": "replay", "file": "/data/replay.local.json", "max_turns": 3}
  ]
}
```

A random job uses the random JSON schema plus `mode`. A replay job requires
exactly one of `recording` (embedded replay JSON) or `file` (a container path),
and optionally `max_turns`. Nested stdin references are not allowed. Absolute
file paths are recommended: relative paths resolve from the container working
directory, `/app`, not the manifest's directory.

The checked-in `example.json` is self-contained and needs no extra recordings:

```sh
# Concurrent mixed execution.
docker compose run --rm app batch /data/example.json --workers 2

# Sequential execution of the same jobs.
docker compose run --rm app batch /data/example.json --workers 1

# The same manifest via stdin.
docker compose run --rm -T app batch - < examples/example.json

# Build a small mixed request directly on the command line.
printf '%s\n' '{"jobs":[{"mode":"random-play","n":2,"seed":42},{"mode":"replay","recording":{"n":1,"turn_order":[],"moves":[]}}]}' | docker compose run --rm -T app batch -
```

All expanded random games and replay jobs use **one shared worker pool**,
not a pool inside each job. Records are ordered by manifest job, then by N and
game number within that job. Every record has a global `game_index` and its
original `job_index`; successful records also identify their game `mode`.

A malformed manifest rejects the entire command. A bad individual job produces
an error record and other jobs continue. An invalid multi-N job produces one
error, not a partially scheduled set of games. Errors detected while preparing
a job have `mode: "error"`. The summary's `games` counts emitted game/error
records; an invalid job counts once because its games were not expanded.
Summary fields are `games`, `succeeded`, `failed`, `wins`, and `stop_reasons`.

## Options, limits, and exit status

| Option | Replay | Random-play | Mixed batch |
| --- | --- | --- | --- |
| Input | One or more file paths, or sole `-` | Positional Ns, or `--input FILE/-` | One manifest path or `-` |
| `--workers` | Shared file pool | Shared game pool | Shared pool across all job types |
| `--max-turns` | Applies to each recording | Applies to each game; JSON uses `max_turns` | Set `max_turns` on individual jobs |
| `--games`, `--seed` | Not applicable | CLI form; JSON uses `games`, `seed` | Set on individual random jobs |

N accepts positive whole-number values: `3`, `3.0`, `"3"`, and `"3.00"`
all normalize to integer 3. Strings allow surrounding whitespace. Fractions,
booleans, zero, negatives, NaN/infinity, and scientific-notation strings are
rejected. Decimal strings are checked exactly, without float rounding.
Positive count/limit options use the same validation. Seeds are integers and
may be negative; JSON seeds cannot be booleans or decimal values.

Configure defaults through environment variables or a Compose `.env` file;
[.env.example](.env.example) lists them:

| Variable | Default | Meaning |
| --- | ---: | --- |
| `HANOI_MAX_N` | 10 | Maximum disks per player |
| `HANOI_MOVES_FACTOR` | 1000 | Per-N action-budget multiplier |
| `HANOI_MAX_MOVES` | 100000 | Absolute action cap per game |

For example, override the container environment for one invocation:

```sh
docker compose run --rm -e HANOI_MAX_MOVES=50 app random-play 3 --seed 42
```

The budget is `min(HANOI_MAX_MOVES, HANOI_MOVES_FACTOR * (2**N - 1))`.
It is a resource limit, not a promise that random play will solve Hanoi.
`max_turns` can lower, but never raise, this budget. In multi-N requests it must
fit every N. Skips and illegal actions both consume a turn.

Stop reasons are `win`, `move_limit`, and (for replay) `input_exhausted`.
A win on the last permitted turn takes precedence over the cap. Hitting the cap
is not a rules-based draw. Invalid actions do not themselves make the CLI fail.

Exit status is 0 for successful execution (including a move-limit stop), 1 when
a replay/mixed batch has any failed input, and 2 for invalid CLI options or an
invalid single input/manifest. Diagnostics go to stderr; JSON results go to stdout.
To save results, append `> results.jsonl` to a batch or random-play command.

## Rules and internal state

A sees `1a – 2 – 3a`; B sees `1b – 2 – 3b`. Pole 2 is the **same stack**
for both players. A starts with odd disks and B with even disks, largest at the
bottom. Disk size is its unique identifier; there is no persistent owner field.

Each supplied turn performs exactly one lift, place, or skip. A player can
hold one disk. A placement needs an empty pole or a strictly larger top disk.
Either player can take any top disk from shared pole 2.

A player wins only when their hand, private pole 1, and the entire shared pole
are empty, while their private pole 3 is nonempty. The original ownership of
disks does not matter. Clearing pole 2 can cause the **other** player to win.
The opponent's private poles and held disk do not block victory. Both players
are checked after a transition; the first winning state ends the game.

### Data models

All models below are frozen, slotted dataclasses. Game schemas live in
[app/schemas.py](app/schemas.py); runtime configuration lives separately in
[app/config.py](app/config.py).

| Model | Fields / representation | Purpose |
| --- | --- | --- |
| `Poles` | `pole_1a`, `pole_2`, `pole_3a`, `pole_1b`, `pole_3b`: tuples of integers | Fixed five-stack board; empty stack is `()` |
| `Hands` | `A`, `B`: integer disk size or `0` | One held disk per player; zero means empty |
| `GameState` | `poles: Poles`, `hands: Hands` | Complete immutable board snapshot |
| `Action` | `kind: str`, optional `pole: str` | Requested action; unsupported strings can represent illegal attempts |
| `PlayerView` | `player`, `pole_1`, `pole_2`, `pole_3`, `hand` | Only the acting player's visible information |
| `StepResult` | `state`, `legal`, `reason`, `winner` | Transition result, separate from the state itself |
| `Settings` | `max_n`, `moves_factor`, `max_moves` | Environment loading and per-game execution budgets |

Pole tuples are ordered bottom to top: `(5, 3, 1)` has disk 1 on top.
A pole cannot be represented by one integer: lifting its top disk must reveal
the rest of the stack. Only hands use the integer-or-zero representation.

Frozen fields and immutable tuples prevent accidental in-place edits; slots
prevent attaching arbitrary fields. They do **not** enforce type annotations
or validate arbitrary manually constructed states. Create states with
`new_game` and advance them through `step`; raw constructors are trusted.

Turn counts, limits, RNG state, and scheduling belong to runners, not
`GameState`. There is no stored current player or winner that could drift out
of sync with the board. Each concurrent game owns its state and random generator.

### Module boundaries and engine API

| Module | Responsibility |
| --- | --- |
| `schemas.py` | Fixed data models and the `Player` type alias |
| `engine.py` | Initialization, views, legal actions, transitions, win checks |
| `config.py` | Settings and execution budgets; no game rules |
| `runner.py` | Replay execution, random agents/scheduler, CPU-capped process execution |
| `batch.py` | Random JSON validation and mixed-job preparation/execution |
| `__main__.py` | CLI parsing, JSON input/output, summaries and exit codes |

Public engine functions are exported from `app`:

```python
new_game(n, *, max_n=10)       # GameState
observe(state, player)        # PlayerView
legal_actions(view)          # tuple[Action, ...]
step(state, player, action)   # StepResult
snapshot(state)              # detached JSON-compatible full-board dictionary
```

A runner selects a player, obtains their view, asks an agent for an action,
then submits that action to `step`. The random agent uses this same interface
as a future external agent: it receives only a restricted view and legal actions,
never the full state. It chooses uniformly from legal actions, including skip.

Illegal actions return the exact unchanged state with `reason="illegal_action"`.
Calling `step` after victory returns `reason="game_over"` without mutation.
Unknown player identifiers raise `ValueError`. The engine does not read the
environment, perform I/O, choose players, or impose a turn pattern.

`snapshot` exposes both players for trusted replay/debugging consumers and CLI
output. It is not an admin account or authentication system. Its lists/dicts are
detached from internal state; agents should never receive this full-board output.

## Design decisions and additions beyond the base assignment

The original assignment required an engine, a replay frontend, a random-play
frontend, and direct engine tests. These are the additional choices we made:

| Decision / extension | Why and trade-off |
| --- | --- |
| Multi-N random requests and repeated games | Compare sizes in one command. `--games` means games per N, not total games. |
| Multiple replay inputs | Run independent recordings together; one bad file does not cancel the rest. |
| JSON random input and mixed batches | Make runs reproducible/shareable and combine random/replay workloads without separate processes per command. |
| CPU-capped process concurrency | Run CPU-bound games independently. One pool per request; explicitly requesting more workers cannot exceed available CPUs. |
| Balanced random turn policy | At equal counts choose randomly; otherwise choose the trailing player. Counts differ by at most one, but ABBA is possible. |
| Per-N and absolute move caps | Bound unsuccessful random walks and oversized replays; a cap is not a game-rule change. |
| Whole-number decimal input | Accept `3.0` and `"3.00"` without permitting fractional disk counts. |
| Seeded runs and ordered JSONL | Reproduce game results across worker counts and stream machine-readable output. Timing is not reproducible. |
| Full-state diagnostic snapshots | Support replay output/debugging without adding an admin role or exposing hidden state to agents. |
| Docker-only uv workflow and multi-stage image | Keep host setup minimal and test dependencies out of the production image. |
| Under 500 production Python lines | Favor focused modules and the standard library over a general framework. Tests are counted separately. |
| One checked-in example | Keep the repository small; generate high-N and error fixtures during tests. |

The scheduler's balance does not remove first-player advantage. With N=1,
A can still win on its second action after A–B–A. It cannot take the first two
turns consecutively under this policy. Replay is not restricted by that policy:
its external turn sequence is authoritative, including A–A.

Worker count is `min(number_of_tasks, requested_or_available_CPUs, available_CPUs)`,
using `os.process_cpu_count()` with fallback 1. A single worker executes directly;
otherwise a spawn-based `ProcessPoolExecutor` uses bounded queued work and
one game per task. Output order may wait behind an earlier slow game.
Files/manifests are read fully into memory; process crashes and memory exhaustion
are not isolated like handled input errors. Concurrent updates to the *same*
game would need a lock or version check; this project runs independent games.

For standalone random requests, game seeds are `base_seed + game_index`.
Within mixed batches, each random job has its own base seed and **job-local**
game index; moving a seeded job in the manifest does not change its games.
Global output indices still identify every expanded task.

The standard library supplies dataclasses, argparse, JSON, RNGs, and process
pools; pytest and Hypothesis supply the test framework/property testing.
There are no third-party runtime dependencies. No web server, persistence,
interactive UI, or authorization layer is included.

## Testing and development

Latest Docker verification: **156 tests passed**. Production Python totals
**472 physical lines**, below the 500-line limit; tests total **786 lines**
separately. The test image contains only the published example, so generated
fixtures do not depend on ignored local files.

```sh
docker compose build app test
docker compose run --rm test
docker compose run --rm test tests/test_engine.py
docker compose run --rm test tests/test_json_jobs.py
```

Tests call the engine directly and cover conservation/stack order, independent
expected legal-action sets, hidden views, illegal moves, opponent-triggered wins,
numeric validation, trailing replay validation, settings, and budget boundaries.
Runner/CLI tests cover actual random transitions, scheduling balance, serial/
parallel equality, input failure isolation, JSON requests, and mixed batches.

High-N fixtures include complete N=3, N=5 and N=10 solutions, plus malformed
inputs, disk transfers, and shared-pole win-blocking cases. They are generated
by test code; no large recordings need to be checked in or present on the host.

The Dockerfile has uv/base, dependency-builder, production-runtime, and test
stages. Python and uv images are pinned by digest; `uv.lock` pins dependencies.
The runtime contains no pytest/Hypothesis or test files.

Count production and test Python separately inside Docker:

```sh
docker compose run --rm --entrypoint uv test run --locked --no-sync python -c \
  'from pathlib import Path; print({d: sum(len(p.read_text().splitlines()) for p in Path(d).rglob("*.py")) for d in ("app", "tests")})'
```

To regenerate the lockfile entirely in Docker:

```sh
docker build --target base -t shared-pole-hanoi-bootstrap .
docker run --rm --mount type=bind,source="$PWD",target=/app shared-pole-hanoi-bootstrap uv lock
docker compose build app test
```

Independent review verification has also exercised every reachable N=1/N=2
state against a separate rules implementation (89,976 action checks). Mutation
checks confirm that always skipping, always submitting an illegal action, and
always selecting A are detected. Deep JSON decoder failures are regression-tested
by deterministic exception injection; actual 100,000-level input was also checked
through single-file/stdin and serial/concurrent batch paths.

## AI use disclosure

OpenAI Codex assisted with implementation changes, code review, test improvements,
and documentation formatting and language improvements. Separate implementation
and review sessions helped identify gaps in test coverage and detect edge cases.
