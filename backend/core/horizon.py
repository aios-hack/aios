"""Process-wide monthly horizon, fixed before importing contracts/models.

Set AIOS_HORIZON_PATH to organizer-specific JSON in a fresh process. Changing
the horizon does not migrate trained weights; the search checks their dates.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import date
from pathlib import Path


@dataclass(frozen=True)
class Horizon:
    t0: date
    n_intervals: int
    n_deck_dates: int
    discount_base_year: int

    @property
    def history_offset(self) -> int:
        return self.n_deck_dates - self.n_intervals - 1


def load_horizon(path: str | None = None) -> Horizon:
    if path is None:
        return Horizon(date(2007, 1, 1), 224, 371, 2007)
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    expected = {"t0", "n_intervals", "n_deck_dates", "discount_base_year"}
    if not isinstance(data, dict) or set(data) != expected:
        raise ValueError(f"horizon must contain exactly {sorted(expected)}")
    t0 = date.fromisoformat(data["t0"])
    for key in expected - {"t0"}:
        if type(data[key]) is not int or data[key] <= 0:
            raise ValueError(f"horizon {key} must be a positive integer")
    result = Horizon(t0, data["n_intervals"], data["n_deck_dates"], data["discount_base_year"])
    if t0.day != 1 or result.history_offset < 0:
        raise ValueError("horizon requires monthly dates and n_deck_dates > n_intervals")
    return result


HORIZON = load_horizon(os.environ.get("AIOS_HORIZON_PATH"))
