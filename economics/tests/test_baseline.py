from __future__ import annotations

import pytest

from economics import (
    OPM_CONTROL_HORIZON_BASE_NPV_RUB,
    TNAV_CONTROL_HORIZON_BASE_NPV_RUB,
    TNAV_CONTROL_START_DISCOUNT_FACTOR,
    TNAV_FULL_PROJECT_BASE_NPV_RUB,
    TNAV_HISTORY_THROUGH_2006_NPV_RUB,
    rebase_control_horizon_to_published_full_project,
)


def test_published_tnav_horizon_rebases_back_to_full_project() -> None:
    assert rebase_control_horizon_to_published_full_project(
        TNAV_CONTROL_HORIZON_BASE_NPV_RUB
    ) == pytest.approx(TNAV_FULL_PROJECT_BASE_NPV_RUB, rel=0.0, abs=1e-6)


def test_published_discount_factor_is_2007_on_1991_basis() -> None:
    assert TNAV_CONTROL_START_DISCOUNT_FACTOR == pytest.approx(
        1.0 / 1.1**16, rel=0.0, abs=1e-15
    )
    assert TNAV_HISTORY_THROUGH_2006_NPV_RUB < TNAV_FULL_PROJECT_BASE_NPV_RUB


def test_opm_and_tnav_baselines_are_close_only_on_the_same_basis() -> None:
    relative_gap = (
        OPM_CONTROL_HORIZON_BASE_NPV_RUB / TNAV_CONTROL_HORIZON_BASE_NPV_RUB
        - 1.0
    )
    assert relative_gap == pytest.approx(-0.002592497672245675, abs=1e-15)
    assert abs(relative_gap) < 0.003
