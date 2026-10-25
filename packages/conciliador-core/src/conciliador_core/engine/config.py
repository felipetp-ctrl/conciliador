"""Configuração do motor de conciliação."""

from dataclasses import dataclass

MAX_TOLERANCE_CENTS = 100
MAX_WINDOW_DAYS = 60


@dataclass(frozen=True)
class MatchConfig:
    days_before: int = 5
    days_after: int = 10
    tolerance_cents: int = 0

    def __post_init__(self) -> None:
        if not 0 <= self.tolerance_cents <= MAX_TOLERANCE_CENTS:
            raise ValueError("tolerance_cents deve estar entre 0 e 100")
        if self.days_before < 0 or self.days_after < 0:
            raise ValueError("days_before e days_after não podem ser negativos")
        if self.days_before > MAX_WINDOW_DAYS or self.days_after > MAX_WINDOW_DAYS:
            raise ValueError("days_before e days_after devem ser no máximo 60")
