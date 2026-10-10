"""Fixed, immutable game data shared by the engine and its consumers."""
from dataclasses import dataclass
from typing import Literal

Player = Literal["A", "B"]


@dataclass(frozen=True, slots=True)
class Poles:
    pole_1a: tuple[int, ...] = ()
    pole_2: tuple[int, ...] = ()
    pole_3a: tuple[int, ...] = ()
    pole_1b: tuple[int, ...] = ()
    pole_3b: tuple[int, ...] = ()


@dataclass(frozen=True, slots=True)
class Hands:
    A: int = 0
    B: int = 0


@dataclass(frozen=True, slots=True)
class GameState:
    poles: Poles
    hands: Hands = Hands()


@dataclass(frozen=True, slots=True)
class Action:
    kind: str
    pole: str | None = None


@dataclass(frozen=True, slots=True)
class PlayerView:
    player: Player
    pole_1: tuple[int, ...]
    pole_2: tuple[int, ...]
    pole_3: tuple[int, ...]
    hand: int


@dataclass(frozen=True, slots=True)
class StepResult:
    state: GameState
    legal: bool
    reason: str | None
    winner: Player | None
