from __future__ import annotations

from backend.contexts.optimization.application.search_use_case import _search_theta
from backend.contexts.constraints.domain.constraints import Constraints


def test_case_compensation_corridor_restricts_r5_search_bounds() -> None:
    theta = _search_theta(
        Constraints(
            infrastructure={
                "compensation_min": 0.85,
                "compensation_max": 1.15,
            }
        )
    )

    assert theta.bounds["r5_compensation_low"] == (0.85, 1.0)
    assert theta.bounds["r5_compensation_high"] == (1.0, 1.15)
    assert theta.values["r5_compensation_low"] == 0.9
    assert theta.values["r5_compensation_high"] == 1.15
