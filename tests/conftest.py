"""Generate replay artifacts in pytest's temporary directory, not the repository."""
import json

import pytest


def recording(n, *steps):
    turns, moves = [], []
    for step in steps:
        player, kind, *pole = step.split()
        turns.append(player)
        moves.append({"kind": kind, **({"pole": pole[0]} if pole else {})})
    return {"n": n, "turn_order": turns, "moves": moves}


def solved(n, player, alternating=False):
    steps = []

    def transfer(size, source, target, spare):
        if not size:
            return
        transfer(size - 1, source, spare, target)
        for action in (f"lift {source}", f"place {target}"):
            steps.append(f"{player} {action}")
            if alternating:
                steps.append(f"{'B' if player == 'A' else 'A'} skip")
        transfer(size - 1, spare, target, source)

    transfer(n, "1" + player.lower(), "3" + player.lower(), "2")
    return recording(n, *(steps[:-1] if alternating else steps))


@pytest.fixture(scope="module")
def examples(tmp_path_factory):
    directory = tmp_path_factory.mktemp("replays")
    blocked = ["B lift 1b", "B place 2", "A lift 1a", "A place 3a"]
    cases = {
        "n1_a_wins": recording("1", "A lift 1a", "B lift 1b", "A place 3a"),
        "n2_b_wins": solved(2, "B"),
        "n3_a_wins": solved(3, "A"),
        "n5_alternating_a_wins": solved(5, "A", alternating=True),
        "n10_b_wins": solved(10, "B"),
        "n3_illegal_moves": recording(3, "A lift 1a", "A place 2", "B lift 1b",
                                      "B place 2", "B place 3a", "A skip"),
        "n1_shared_blocks_win": recording(1, *blocked),
        "n1_opponent_wins_early": recording(1, *blocked, "B lift 2", "B place 3b", "A skip"),
        "n2_shared_disk_transfer": recording(2, "B lift 1b", "B place 2", "A lift 2", "A place 3a"),
        "n10_empty_recording": recording("10"),
        "invalid/fractional_n": recording(3.5),
        "invalid/n_above_max": recording(11),
        "invalid/mismatched_turns": {"n": 1, "turn_order": ["A"], "moves": []},
    }
    for name, data in cases.items():
        path = directory / f"{name}.json"
        path.parent.mkdir(exist_ok=True)
        path.write_text(json.dumps(data))
    return directory
