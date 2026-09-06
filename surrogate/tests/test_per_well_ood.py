from __future__ import annotations

from datetime import date, timedelta

from contracts import Availability, OperatingStatus, Role
from surrogate.features import SurrogateInput, WellStepFeatures
from surrogate.ood import NUMERIC_FEATURES
from surrogate.per_well_ood import PerWellInputDomain


def _candidate(setpoint: float) -> SurrogateInput:
    start = date(2007, 1, 1)
    node = WellStepFeatures(
        control_step=0,
        interval_start=start,
        interval_end=start + timedelta(days=31),
        well="A",
        availability=Availability.AVAILABLE,
        role=Role.PROD,
        operating_status=OperatingStatus.OPEN,
        setpoint_m3_per_day=setpoint,
        effective_target_rate_m3_per_day=setpoint,
        cumulative_target_liquid_m3=0.0,
        cumulative_target_injection_m3=0.0,
        cumulative_neighbor_injection_m3=0.0,
        current_neighbor_injection_m3_per_day=0.0,
        event_count=1,
        fixed_event_count=0,
        static_values=(1.0, 2.0, 3.0),
        lambda_window_start=start,
        lambda_window_end=start + timedelta(days=365),
    )
    return SurrogateInput(
        canonical_schedule_hash="hash",
        wells=("A",),
        static_feature_names=("x", "y", "id"),
        nodes=(node,),
        lambda_edges=(),
    )


def _domain() -> PerWellInputDomain:
    lows = [0.0] * len(NUMERIC_FEATURES)
    highs = [10.0] * len(NUMERIC_FEATURES)
    highs[0] = 4.0
    highs[1] = 4.0
    return PerWellInputDomain(
        dataset_hash="dataset",
        wells=("A",),
        feature_names=NUMERIC_FEATURES,
        lows_log1p=(tuple(lows),),
        highs_log1p=(tuple(highs),),
        threshold=0.05,
        n_fit_scenarios=10,
        threshold_quantile=0.95,
        validation_scenario_count=5,
        validation_inside_count=5,
    )


def test_per_well_domain_detects_a_well_specific_exceedance(tmp_path) -> None:
    domain = _domain()
    inside = domain.score(_candidate(20.0))
    outside = domain.score(_candidate(100.0))

    assert inside.score == 0.0
    assert outside.score > domain.threshold
    assert outside.worst is not None
    assert outside.worst.feature in {
        "per_well:setpoint_m3_per_day",
        "per_well:effective_target_rate_m3_per_day",
    }

    path = domain.save(tmp_path / "domain.json")
    assert PerWellInputDomain.load(path) == domain
