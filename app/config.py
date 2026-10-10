"""Runtime configuration and per-game execution budgets."""
from dataclasses import dataclass, fields
import os

from .engine import positive_int


@dataclass(frozen=True, slots=True)
class Settings:
    max_n: int = 10
    moves_factor: int = 1000
    max_moves: int = 100000

    @classmethod
    def from_env(cls):
        return cls(**{field.name: positive_int(
            os.environ.get(f"HANOI_{field.name.upper()}", field.default), field.name)
            for field in fields(cls)})

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
