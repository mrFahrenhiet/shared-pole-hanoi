from dataclasses import FrozenInstanceError, fields

import pytest
from hypothesis import given, settings, strategies as st

from app import (Action, GameState, Hands, PlayerView, Poles, legal_actions, new_game,
                   observe, snapshot, step)


def test_initialization_and_numeric_strings():
    state = new_game(" 3 ")
    assert state == GameState(Poles(pole_1a=(5, 3, 1), pole_1b=(6, 4, 2)))
    assert len(new_game(10).poles.pole_1a) == 10
    assert new_game("003") == state
    with pytest.raises(ValueError):
        new_game(11)
    assert len(new_game(11, max_n=11).poles.pole_1a) == 11


@pytest.mark.parametrize("n", [3.0, "3.0", "3.00", " 003.000 ", "3." + "0" * 50])
def test_whole_number_decimals(n):
    assert new_game(n) == new_game(3)


@pytest.mark.parametrize("n", [0, -1, True, False, 1.5, "1.5", "1e0", "-1", "", None,
                              float("nan"), float("inf"), float("-inf"),
                              "3.00000000000000000001", "3.", "3.0.0", "0.00"])
def test_invalid_n(n):
    with pytest.raises(ValueError):
        new_game(n)


def test_immutable_views_and_detached_snapshot():
    state = new_game(2)
    view = observe(state, "A")
    assert {f.name for f in fields(view)} == {"player", "pole_1", "pole_2", "pole_3", "hand"}
    assert view.pole_1 == (3, 1) and view.hand == 0
    with pytest.raises(FrozenInstanceError):
        state.hands.A = 1
    with pytest.raises((AttributeError, TypeError)):
        state.poles.pole_4 = ()
    with pytest.raises(TypeError):
        state.poles.pole_1a[0] = 99
    full = snapshot(state)
    full["poles"]["1a"].clear()
    full["hands"]["B"] = 99
    assert state == new_game(2)


@pytest.mark.parametrize("player,action", [
    ("A", Action("lift", "2")), ("A", Action("place", "3a")),
    ("B", Action("lift", "1a")), ("B", Action("place", "3a")),
    ("A", Action("lift", "1b")), ("A", Action("lift", "4")),
    ("A", Action("dance")), ("A", Action("skip", "2")),
])
def test_illegal_actions_preserve_state(player, action):
    state = new_game(2)
    outcome = step(state, player, action)
    assert not outcome.legal and outcome.state is state and outcome.winner is None


def test_full_hand_and_larger_placement():
    state = step(new_game(2), "A", Action("lift", "1a")).state
    assert not step(state, "A", Action("lift", "1a")).legal
    state = GameState(Poles(pole_1a=(1,), pole_1b=(4, 2)), Hands(A=3))
    assert not step(state, "A", Action("place", "1a")).legal
    assert step(state, "A", Action("place", "2")).legal


def test_arbitrary_turns_win_and_finished_rejection():
    state = step(new_game(1), "A", Action("lift", "1a")).state
    outcome = step(state, "A", Action("place", "3a"))
    assert outcome.winner == "A"
    later = step(outcome.state, "B", Action("lift", "1b"))
    assert later.reason == "game_over" and later.state is outcome.state


def test_shared_disk_can_be_taken_by_other_player_and_enable_opponent_win():
    state = GameState(Poles(pole_2=(2,), pole_3a=(1,)))
    assert step(state, "B", Action("skip")).winner is None
    taken = step(state, "B", Action("lift", "2"))
    assert taken.winner == "A" and taken.state.hands.B == 2
    state = GameState(Poles(pole_1a=(1,), pole_2=(2,)))
    taken = step(state, "A", Action("lift", "2"))
    assert taken.legal and taken.state.hands.A == 2
    placed = step(taken.state, "A", Action("place", "3a"))
    assert placed.legal and placed.state.poles.pole_3a == (2,)


def test_original_ownership_not_required_and_empty_destination_does_not_win():
    state = GameState(Poles(pole_1b=(1,), pole_3a=(2,)))
    assert step(state, "B", Action("skip")).winner == "A"
    state = GameState(Poles(pole_1b=(2, 1)))
    assert step(state, "A", Action("skip")).winner is None


def test_opponents_hand_and_private_poles_do_not_block_win():
    state = new_game(1)
    for player, action in [("A", Action("lift", "1a")), ("B", Action("lift", "1b")),
                           ("A", Action("place", "3a"))]:
        outcome = step(state, player, action)
        state = outcome.state
    assert outcome.winner == "A" and state.hands.B == 2


def test_unknown_player_is_caller_error():
    with pytest.raises(ValueError):
        step(new_game(1), "C", Action("skip"))


@pytest.mark.parametrize("player", ["A", "B"])
@pytest.mark.parametrize("stacks,hand,kind,poles", [
    (((), (), ()), 0, "lift", ()),
    (((5, 1), (4, 2), (3,)), 0, "lift", ("1", "2", "3")),
    (((5, 3), (4, 2), ()), 1, "place", ("1", "2", "3")),
    (((5, 1), (4, 2), ()), 3, "place", ("3",)),
])
def test_legal_actions_match_independent_expected_sets(player, stacks, hand, kind, poles):
    view = PlayerView(player, *stacks, hand)
    expected = {Action("skip")} | {
        Action(kind, pole if pole == "2" else pole + player.lower()) for pole in poles}
    assert set(legal_actions(view)) == expected


@settings(max_examples=60, deadline=None)
@given(st.integers(1, 5), st.lists(st.tuples(st.sampled_from(["A", "B"]),
                                          st.integers(0, 100)), max_size=150))
def test_legal_sequences_preserve_disks_and_stack_order(n, choices):
    state = new_game(n)
    for player, index in choices:
        actions = legal_actions(observe(state, player))
        outcome = step(state, player, actions[index % len(actions)])
        state = outcome.state
        full = snapshot(state)
        disks = [disk for stack in full["poles"].values() for disk in stack]
        disks += [disk for disk in full["hands"].values() if disk]
        assert sorted(disks) == list(range(1, 2 * n + 1))
        for stack in full["poles"].values():
            assert all(a > b for a, b in zip(stack, stack[1:]))
        if outcome.winner:
            break
