"""Pure rules and immutable state transitions for shared-pole Hanoi."""
from dataclasses import replace

from .schemas import Action, GameState, Player, PlayerView, Poles, StepResult


def positive_int(value: object, name: str = "value") -> int:
    if isinstance(value, str) and value.strip().isascii() and value.strip().isdecimal():
        value = int(value.strip())
    if type(value) is not int or value <= 0:
        raise ValueError(f"{name} must be a positive integer or decimal integer string")
    return value


def new_game(n: int | str, *, max_n: int = 10) -> GameState:
    n = positive_int(n, "N")
    if n > positive_int(max_n, "max_n"):
        raise ValueError(f"N must not exceed {max_n}")
    return GameState(Poles(pole_1a=tuple(range(2 * n - 1, 0, -2)),
                           pole_1b=tuple(range(2 * n, 0, -2))))


def observe(state: GameState, player: Player) -> PlayerView:
    if player not in ("A", "B"):
        raise ValueError("player must be A or B")
    suffix = player.lower()
    return PlayerView(player, getattr(state.poles, f"pole_1{suffix}"),
                      state.poles.pole_2, getattr(state.poles, f"pole_3{suffix}"),
                      getattr(state.hands, player))


def legal_actions(view: PlayerView) -> tuple[Action, ...]:
    actions = [Action("skip")]
    poles = ((f"1{view.player.lower()}", view.pole_1), ("2", view.pole_2),
             (f"3{view.player.lower()}", view.pole_3))
    for pole, stack in poles:
        if not view.hand and stack:
            actions.append(Action("lift", pole))
        elif view.hand and (not stack or view.hand < stack[-1]):
            actions.append(Action("place", pole))
    return tuple(actions)


def winner(state: GameState) -> Player | None:
    for player in ("A", "B"):
        view = observe(state, player)
        if not view.hand and not view.pole_1 and not view.pole_2 and view.pole_3:
            return player
    return None


def step(state: GameState, player: Player, action: Action) -> StepResult:
    view = observe(state, player)
    won = winner(state)
    if won:
        return StepResult(state, False, "game_over", won)
    if action not in legal_actions(view):
        return StepResult(state, False, "illegal_action", None)
    if action.kind == "skip":
        return StepResult(state, True, None, None)
    field = f"pole_{action.pole}"
    stack = getattr(state.poles, field)
    if action.kind == "lift":
        stack, hand = stack[:-1], stack[-1]
    else:
        stack, hand = (*stack, view.hand), 0
    updated = GameState(replace(state.poles, **{field: stack}),
                        replace(state.hands, **{player: hand}))
    return StepResult(updated, True, None, winner(updated))


def snapshot(state: GameState) -> dict:
    return {"poles": {pole: list(getattr(state.poles, f"pole_{pole}"))
                      for pole in ("1a", "2", "3a", "1b", "3b")},
            "hands": {"A": state.hands.A, "B": state.hands.B}}
