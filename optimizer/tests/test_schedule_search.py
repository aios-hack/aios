from __future__ import annotations

import hashlib
from types import SimpleNamespace

import pytest
import torch

from contracts import (
    Availability,
    Constraints,
    ControlEvent,
    EventKind,
    FixedDeckEvent,
    OperatingStatus,
    Role,
    Schedule,
    ScheduleMeta,
    WellState,
)
from optimizer.schedule_search import (
    OutOfDomainScheduleError,
    ScheduleSearchError,
    PhysicallyImpossibleScheduleError,
    _enforce_ood_threshold,
    _enforce_physics,
    _enforce_scenario_ood,
    admission_reason,
    _field_limit_for_step,
    _flow_start_steps,
    _outage_events,
    _produced_water_rate_m3_per_day,
    _scale_step_injection_to_limit,
    _validate_npv_head_compatibility,
)
from policy.state import PolicyState, WellObservation
from surrogate.ood import Exceedance, OodScore
from surrogate.physics_checks import Invariant, PhysicsFlag, PhysicsReport, Severity


def test_ood_threshold_allows_inside_and_disabled_gate() -> None:
    outside = OodScore(
        score=0.25,
        exceedances=(
            Exceedance(
                feature="setpoint_m3_per_day",
                well="P1",
                control_step=2,
                value=125.0,
                low=0.0,
                high=100.0,
                score=0.25,
            ),
        ),
        n_nodes=1,
    )

    _enforce_ood_threshold(outside, None)
    _enforce_ood_threshold(outside, 0.25)


def test_ood_threshold_rejects_before_surrogate_value_is_used() -> None:
    outside = OodScore(
        score=0.25,
        exceedances=(
            Exceedance(
                feature="setpoint_m3_per_day",
                well="P1",
                control_step=2,
                value=125.0,
                low=0.0,
                high=100.0,
                score=0.25,
            ),
        ),
        n_nodes=1,
    )

    with pytest.raises(OutOfDomainScheduleError) as caught:
        _enforce_ood_threshold(outside, 0.0)

    assert caught.value.score == pytest.approx(0.25)
    assert "setpoint_m3_per_day" in caught.value.description
    assert "P1" in str(caught.value)


def test_corrected_npv_head_may_use_augmented_data_with_exact_context(tmp_path) -> None:
    context = tmp_path / "feature_context.json"
    context.write_bytes(b"context")
    axes = {
        "wells": ("A", "B"),
        "static_feature_names": ("i", "j", "depth"),
    }
    model = SimpleNamespace(dataset_hash="historical", **axes)
    head = SimpleNamespace(
        dataset_hash="historical-plus-blind1",
        feature_context_sha256=hashlib.sha256(b"context").hexdigest(),
        **axes,
    )

    _validate_npv_head_compatibility(head, model, context)
    context.write_bytes(b"changed")
    with pytest.raises(ScheduleSearchError, match="feature context"):
        _validate_npv_head_compatibility(head, model, context)

    legacy = SimpleNamespace(dataset_hash="other", feature_context_sha256="", **axes)
    with pytest.raises(ScheduleSearchError, match="разных данных"):
        _validate_npv_head_compatibility(legacy, model, context)


def test_physical_npv_blend_pins_exact_trajectory_ensemble(tmp_path) -> None:
    context = tmp_path / "feature_context.json"
    context.write_bytes(b"context")
    axes = {
        "wells": ("A", "B"),
        "static_feature_names": ("i", "j", "depth"),
    }
    model = SimpleNamespace(
        dataset_hash="historical",
        version="a" * 64,
        **axes,
    )
    head = SimpleNamespace(
        dataset_hash="historical-plus-disclosed",
        feature_context_sha256=hashlib.sha256(b"context").hexdigest(),
        physical_npv_weight=0.2,
        physical_ensemble_version="a" * 64,
        **axes,
    )

    _validate_npv_head_compatibility(head, model, context)
    head.physical_ensemble_version = "b" * 64
    with pytest.raises(ScheduleSearchError, match="trajectory ensemble"):
        _validate_npv_head_compatibility(head, model, context)


def _observation(
    well: str,
    role: Role,
    *,
    is_open: bool = True,
    liquid: float = 0.0,
    oil: float = 0.0,
) -> WellObservation:
    return WellObservation(
        well=well,
        role=role,
        is_open=is_open,
        liquid_rate_m3_per_day=liquid,
        oil_rate_t_per_day=oil,
        injection_rate_m3_per_day=0.0,
        setpoint_m3_per_day=0.0,
    )


def test_produced_water_counts_only_open_producers() -> None:
    policy_state = PolicyState(
        control_step=0,
        wells={
            "P1": _observation("P1", Role.PROD, liquid=100.0, oil=45.0),
            "P2": _observation(
                "P2", Role.PROD, is_open=False, liquid=100.0, oil=0.0
            ),
            "I1": _observation("I1", Role.INJ, liquid=100.0, oil=0.0),
        },
    )
    assert _produced_water_rate_m3_per_day(policy_state, 0.9) == pytest.approx(
        50.0
    )


def test_field_limit_intersects_physics_case_and_available_water() -> None:
    constraints = Constraints(
        injection_limits={2007: 50.0},
        infrastructure={
            "water_reinjection_fraction": 1.0,
            "external_water_m3_per_day": 5.0,
        },
    )
    assert _field_limit_for_step(
        physical_limit_m3_per_day=100.0,
        constraints=constraints,
        year=2007,
        control_step=0,
        produced_water_by_step=[40.0],
    ) == 45.0


def test_field_limit_with_lag_has_only_external_water_on_first_step() -> None:
    constraints = Constraints(
        infrastructure={
            "water_reinjection_fraction": 1.0,
            "water_reinjection_lag_steps": 1,
            "external_water_m3_per_day": 5.0,
        }
    )
    assert _field_limit_for_step(
        physical_limit_m3_per_day=100.0,
        constraints=constraints,
        year=2007,
        control_step=0,
        produced_water_by_step=[40.0],
    ) == 5.0


def test_outage_events_force_zero_and_shut() -> None:
    policy_state = PolicyState(
        control_step=3,
        wells={"I1": _observation("I1", Role.INJ)},
    )
    events = _outage_events(policy_state, frozenset({"I1"}))
    assert [(event.kind, event.value) for event in events] == [
        (EventKind.SET_RATE, 0.0),
        (EventKind.SHUT, None),
    ]


def test_flow_starts_only_after_first_completion() -> None:
    schedule = Schedule(
        meta=ScheduleMeta(wells=("P1",)),
        initial_state={
            "P1": WellState(
                availability=Availability.NOT_COMMISSIONED,
                role=Role.NONE,
                operating_status=OperatingStatus.SHUT,
                setpoint=0.0,
            )
        },
        fixed_deck_events=(
            FixedDeckEvent(0, "P1", "WCONPROD", ("OPEN",)),
            FixedDeckEvent(60, "P1", "COMPDAT", ("1", "1")),
        ),
        control_events=(),
    )
    assert _flow_start_steps(schedule, {"P1": (0.0, 0.0, 0.0)}) == {"P1": 60}


def test_dense_injection_layer_is_scaled_to_water_limit() -> None:
    pending = {
        (0, "I1", EventKind.SET_RATE): ControlEvent(
            0, "I1", EventKind.SET_RATE, 80.0
        ),
        (0, "I1", EventKind.OPEN): ControlEvent(0, "I1", EventKind.OPEN),
        (0, "I2", EventKind.SET_RATE): ControlEvent(
            0, "I2", EventKind.SET_RATE, 20.0
        ),
    }
    current_open = {"I1": True, "I2": True}
    current_setpoint = {"I1": 80.0, "I2": 20.0}
    total = _scale_step_injection_to_limit(
        pending,
        0,
        50.0,
        current_is_open=current_open,
        current_setpoint=current_setpoint,
    )
    assert total == pytest.approx(50.0)
    assert pending[(0, "I1", EventKind.SET_RATE)].value == pytest.approx(40.0)
    assert pending[(0, "I2", EventKind.SET_RATE)].value == pytest.approx(10.0)


# --- S-04: физический гейт кандидатов -----------------------------------------


def _physics_report(
    counts: dict[str, int] | None = None,
    *,
    evaluated: tuple[Invariant, ...] = tuple(Invariant),
    skipped: dict[str, str] | None = None,
    examples: tuple[PhysicsFlag, ...] = (),
) -> PhysicsReport:
    return PhysicsReport(
        counts=counts or {},
        examples=examples,
        evaluated=evaluated,
        skipped=skipped or {},
        n_nodes=23072,
        n_wells=103,
    )


def test_physics_gate_passes_a_clean_prediction() -> None:
    _enforce_physics(_physics_report(), True)


def test_physics_gate_ignores_warnings() -> None:
    """Забойное вне предела дека — смена режима в OPM, а не запрет кандидата."""

    _enforce_physics(_physics_report({Invariant.BHP_LIMIT.value: 1219}), True)


def test_physics_gate_rejects_blocking_violation_with_reason() -> None:
    flag = PhysicsFlag(
        invariant=Invariant.WATERCUT_RANGE,
        severity=Severity.BLOCKING,
        well="42",
        observed=-0.31,
        limit=0.0,
        detail="нефти 120.0 м³ при жидкости 90.0 м³: обводнённость -0.333333 меньше нуля",
        control_step=17,
    )
    report = _physics_report(
        {Invariant.WATERCUT_RANGE.value: 3, Invariant.BHP_LIMIT.value: 8},
        examples=(flag,),
    )
    with pytest.raises(PhysicallyImpossibleScheduleError) as error:
        _enforce_physics(report, True)

    message = str(error.value)
    assert "WATERCUT_RANGE×3" in message
    assert "BHP_LIMIT" not in message  # предупреждения в причину отказа не идут
    assert "скважина 42, шаг 17" in message
    assert error.value.counts == {Invariant.WATERCUT_RANGE.value: 3}


def test_physics_gate_can_be_disabled_for_measurement() -> None:
    report = _physics_report({Invariant.WATERCUT_RANGE.value: 3})
    _enforce_physics(report, False)


def test_search_gate_does_not_demand_completeness() -> None:
    """В поиске сравнивать не с чем: differential пропущены, но это не отказ."""

    report = _physics_report(
        evaluated=(
            Invariant.NON_NEGATIVE,
            Invariant.WATERCUT_RANGE,
            Invariant.CUMULATIVE_MONOTONIC,
            Invariant.SHUT_WELL_FLOW,
            Invariant.BHP_LIMIT,
        ),
        skipped={
            Invariant.INJECTION_RESPONSE.value: "определён только на паре",
            Invariant.MATERIAL_BALANCE.value: "определён только на паре",
        },
    )
    assert report.complete is False
    _enforce_physics(report, True)


def test_opm_admission_demands_completeness() -> None:
    """А вот в пакет OPM неполная проверка не пускает: прогон стоит 15 минут."""

    report = _physics_report(
        evaluated=(Invariant.NON_NEGATIVE,),
        skipped={Invariant.MATERIAL_BALANCE.value: "кандидат меняет не только закачку"},
    )
    assert report.admissible is False
    assert "проверка неполна" in admission_reason(report)
    assert "кандидат меняет не только закачку" in admission_reason(report)


def test_opm_admission_names_the_blocking_invariants() -> None:
    report = _physics_report(
        {Invariant.MATERIAL_BALANCE.value: 1, Invariant.BHP_LIMIT.value: 9}
    )
    reason = admission_reason(report)

    assert reason == "блокирующие нарушения: MATERIAL_BALANCE×1"


def test_opm_admission_admits_a_complete_clean_report() -> None:
    assert admission_reason(_physics_report()) == (
        "все семь инвариантов посчитаны, блокирующих нарушений нет"
    )


# --- S-06: сценарный OOD ------------------------------------------------------


def test_scenario_ood_is_optional_and_silent_without_a_domain() -> None:
    """Без обученной плотности проверка молчит, а не выдумывает оценку."""

    _enforce_scenario_ood(SimpleNamespace(), SimpleNamespace(wells=()), None)


def test_scenario_ood_rejects_a_joint_shift_component_ranges_miss(monkeypatch) -> None:
    """Ровно тот случай, который покомпонентный min/max пропускает.

    Каждый признак по отдельности внутри обучающего диапазона — `OodScore`
    молчит, — но расписание целиком относится к режиму, которого в обучении не
    было. Числа взяты с замера на кандидатах контура: порог 11.4167,
    оценка 117.013.
    """

    import optimizer.schedule_search as module

    monkeypatch.setattr(module, "_features", lambda *a, **k: (torch.zeros(1), torch.zeros(1)))
    monkeypatch.setattr(
        module, "scenario_feature_vector", lambda *a, **k: torch.zeros(2908)
    )
    domain = SimpleNamespace(
        threshold=11.4167,
        threshold_quantile=0.95,
        feature_width=2908,
        score=lambda vector: 117.013,
    )
    with pytest.raises(OutOfDomainScheduleError) as error:
        module._enforce_scenario_ood(
            SimpleNamespace(), SimpleNamespace(wells=("A",)), domain
        )

    message = str(error.value)
    assert "совместная плотность" in message
    assert "11.42" in message  # порог назван, а не только оценка
    assert error.value.score == pytest.approx(117.013)


def test_scenario_ood_admits_a_candidate_inside_the_density(monkeypatch) -> None:
    import optimizer.schedule_search as module

    monkeypatch.setattr(module, "_features", lambda *a, **k: (torch.zeros(1), torch.zeros(1)))
    monkeypatch.setattr(
        module, "scenario_feature_vector", lambda *a, **k: torch.zeros(2908)
    )
    domain = SimpleNamespace(
        threshold=11.4167,
        threshold_quantile=0.95,
        feature_width=2908,
        score=lambda vector: 8.0,
    )
    module._enforce_scenario_ood(
        SimpleNamespace(), SimpleNamespace(wells=("A",)), domain
    )


# --- incumbent-гейт ------------------------------------------------------------


def test_incumbent_gate_arithmetic_compares_like_with_like() -> None:
    """Суррогат кандидата против суррогата эталона, а не против OPM-эталона.

    На G10 все 40 кандидатов были хуже эталона на 1.036 млрд, и поиск всё
    равно вернул максимум прогноза: сравнения с опорой в протоколе не было.
    Сравнивать при этом суррогатный ЧДД кандидата с настоящим ЧДД эталона
    нельзя — разница источников спрячет разницу расписаний.
    """

    baseline_surrogate = 11.84e9
    baseline_opm = 11.87e9
    candidate_surrogate = 11.80e9

    # Правильное сравнение: кандидат хуже эталона, гейт обязан сработать.
    assert candidate_surrogate - baseline_surrogate < 0.0
    # Неправильное сравнение дало бы тот же знак здесь, но в общем случае нет:
    # разрыв источников на manifold оптимизатора достигал 431% (§4.3 карточки).
    assert abs(baseline_opm - baseline_surrogate) > 0.0


def test_baseline_counts_cannot_excuse_a_blocking_violation() -> None:
    baseline = {Invariant.SHUT_WELL_FLOW.value: 58}
    same = _physics_report({Invariant.SHUT_WELL_FLOW.value: 58})
    with pytest.raises(PhysicallyImpossibleScheduleError):
        _enforce_physics(same, True, baseline)


def test_physics_gate_rejects_violations_beyond_the_baseline() -> None:
    baseline = {Invariant.SHUT_WELL_FLOW.value: 58}
    worse = _physics_report({Invariant.SHUT_WELL_FLOW.value: 61})

    with pytest.raises(PhysicallyImpossibleScheduleError) as error:
        _enforce_physics(worse, True, baseline)

    # All violations remain visible; baseline counts do not waive them.
    assert error.value.counts == {Invariant.SHUT_WELL_FLOW.value: 61}


def test_physics_gate_rejects_a_kind_the_baseline_does_not_have_at_all() -> None:
    baseline = {Invariant.SHUT_WELL_FLOW.value: 58}
    new_kind = _physics_report(
        {Invariant.SHUT_WELL_FLOW.value: 58, Invariant.WATERCUT_RANGE.value: 2}
    )

    with pytest.raises(PhysicallyImpossibleScheduleError) as error:
        _enforce_physics(new_kind, True, baseline)

    assert error.value.counts == {Invariant.SHUT_WELL_FLOW.value: 58, Invariant.WATERCUT_RANGE.value: 2}
