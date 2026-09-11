from __future__ import annotations

import ast
import inspect
import typing
import json
from dataclasses import dataclass, fields
from datetime import date
from pathlib import Path
from types import SimpleNamespace
from typing import Mapping, Sequence

import pytest

from backend.core.contracts import (
    Availability,
    canonical_bytes,
    ControlEvent,
    EventKind,
    FixedDeckEvent,
    hash_schedule,
    Lambda,
    N_INTERVALS,
    OperatingStatus,
    Role,
    Schedule,
    ScheduleMeta,
    Theta,
    WellState,
)
from backend.contexts.optimization.application import environment as _environment
from backend.contexts.optimization.application import search_use_case as _search_use_case

SEARCH_SOURCE = Path(_environment.__file__)
RUN_SOURCE = Path(_search_use_case.__file__)


def _module_ast(path: Path) -> ast.Module:
    return ast.parse(path.read_text(encoding="utf-8"))


def _class_def(module: ast.Module, name: str) -> ast.ClassDef:
    for node in module.body:
        if isinstance(node, ast.ClassDef) and node.name == name:
            return node
    raise AssertionError(f"класс {name} не найден")


def _function_def(module: ast.Module, name: str) -> ast.FunctionDef:
    for node in module.body:
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return node
    raise AssertionError(f"функция {name} не найдена")


def _annotations(node: ast.ClassDef) -> dict[str, str]:
    return {
        statement.target.id: ast.unparse(statement.annotation)
        for statement in node.body
        if isinstance(statement, ast.AnnAssign)
        and isinstance(statement.target, ast.Name)
    }


def _minimal_schedule() -> Schedule:
    initial_state = {
        "P1": WellState(
            availability=Availability.AVAILABLE,
            role=Role.PROD,
            operating_status=OperatingStatus.OPEN,
            setpoint=50.0,
        )
    }
    return Schedule(
        meta=ScheduleMeta(wells=("P1",)),
        initial_state=initial_state,
        fixed_deck_events=(),
        control_events=(),
    )


def test_search_environment_declares_the_anchor_with_check_pair_types() -> None:
    environment = _class_def(_module_ast(SEARCH_SOURCE), "SearchEnvironment")
    annotations = _annotations(environment)

    assert annotations["reference_schedule"] == "Schedule | None"
    assert annotations["reference_response"] == "RawModelOutput | None"
    assert annotations["provenance"] == "Mapping[str, str]"


def test_check_pair_accepts_exactly_those_types() -> None:
    physics = pytest.importorskip(
        "backend.contexts.surrogate.domain.physics_checks",
        reason="физические проверки суррогата требуют torch (extras ml)",
    )
    search = pytest.importorskip(
        "backend.contexts.optimization.application.environment",
        reason="сквозной поиск требует torch (extras ml)",
    )
    hints = typing.get_type_hints(physics.check_pair)

    assert hints["reference"] is physics.RawModelOutput
    assert hints["reference_schedule"] is Schedule

    field_types = {item.name: item.type for item in fields(search.SearchEnvironment)}
    assert field_types["reference_response"] == "RawModelOutput | None"
    assert field_types["reference_schedule"] == "Schedule | None"


def test_missing_anchor_is_none_and_marked_in_provenance() -> None:
    search = pytest.importorskip(
        "backend.contexts.optimization.application.environment",
        reason="сквозной поиск требует torch (extras ml)",
    )

    class BrokenModel:
        def predict(self, model_input):
            raise ValueError("чекпойнт не совпадает с расписанием")

    class BrokenContext:
        context = object()

    reference_schedule, reference_response, origin = search._build_reference(
        _minimal_schedule(), BrokenContext(), BrokenModel()
    )

    assert reference_schedule is None
    assert reference_response is None
    assert origin.startswith("absent:")


def test_absent_anchor_is_visible_in_environment_provenance() -> None:
    load_environment = _function_def(_module_ast(SEARCH_SOURCE), "load_environment")
    source = ast.unparse(load_environment)

    assert "_build_reference" in source
    assert "reference_origin" in source
    assert '"reference"' in source or "'reference'" in source


def test_evaluator_exposes_the_anchor() -> None:
    make_evaluator = _function_def(_module_ast(SEARCH_SOURCE), "make_evaluator")
    source = ast.unparse(make_evaluator)

    assert "evaluator.reference_schedule = env.reference_schedule" in source
    assert "evaluator.reference_response = env.reference_response" in source


@dataclass(frozen=True, slots=True)
class _Outcome:
    schedule: Schedule
    theta: Theta
    predicted_npv: float
    schedule_hash: str
    provenance: dict[str, str]
    evaluations: int
    converged: bool
    self_consistent: bool
    static_violations: int | None
    dynamic_blocking_violations: int | None
    incumbent_history: tuple[object, ...] = ()


def _run_real_main(out: Path, outcome: _Outcome) -> dict[str, object]:
    module = _module_ast(RUN_SOURCE)
    main = _function_def(module, "main")
    namespace: dict[str, object] = {
        "sys": SimpleNamespace(argv=["search_run", "5"]),
        "Path": Path,
        "json": json,
        "BUDGET": 120,
        "SEED": 20260816,
        "SEARCH_CAP": 2,
        "FINAL_CAP": 8,
        "BASE_NPV": 11_873_122_324.91,
        "SEARCH_RESULT": out,
        "canonical_bytes": canonical_bytes,
        "run_search": lambda **_: outcome,
        "print": lambda *args, **kwargs: None,
    }
    exec(compile(ast.Module(body=[main], type_ignores=[]), str(RUN_SOURCE), "exec"), namespace)
    assert namespace["main"]() == 0
    return json.loads(out.read_text(encoding="utf-8"))


def _outcome(static: int | None, dynamic: int | None) -> _Outcome:
    return _Outcome(
        schedule=_minimal_schedule(),
        theta=Theta(values={"a": 1.0}, bounds={"a": (0.0, 2.0)}),
        predicted_npv=1.0,
        schedule_hash="deadbeef",
        provenance={"model_version": "test"},
        evaluations=3,
        converged=True,
        self_consistent=True,
        static_violations=static,
        dynamic_blocking_violations=dynamic,
    )


def test_cmaes_artifact_carries_the_real_violation_counts(tmp_path) -> None:
    payload = _run_real_main(tmp_path / "cmaes.json", _outcome(7, 4))

    assert payload["static_violations"] == 7
    assert payload["dynamic_blocking_violations"] == 4


def test_uncounted_violations_are_null_and_never_zero(tmp_path) -> None:
    payload = _run_real_main(tmp_path / "cmaes.json", _outcome(None, None))

    assert payload["static_violations"] is None
    assert payload["dynamic_blocking_violations"] is None


def test_zero_is_written_only_when_zero_was_measured(tmp_path) -> None:
    payload = _run_real_main(tmp_path / "cmaes.json", _outcome(0, 0))

    assert payload["static_violations"] == 0
    assert payload["dynamic_blocking_violations"] == 0


def test_literal_zero_counts_are_gone_from_the_artifact_writer() -> None:
    main = _function_def(_module_ast(RUN_SOURCE), "main")
    source = ast.unparse(main)

    assert "'static_violations': 0" not in source
    assert "'dynamic_blocking_violations': 0" not in source
    assert "outcome.static_violations" in source
    assert "outcome.dynamic_blocking_violations" in source


def test_selected_finalist_counts_reach_the_outcome() -> None:
    run_search = _function_def(_module_ast(RUN_SOURCE), "run_search")
    source = ast.unparse(run_search)

    assert "static_violations=len(check.violations)" in source
    assert "dynamic_blocking_violations=len(surrogate_blocking)" in source


_PHYSICS_CLASSES = (
    "ScheduleSearchError",
    "PhysicallyImpossibleScheduleError",
    "MissingReferenceError",
)


_PHYSICS_FUNCTIONS = (
    "missing_invariants",
    "_incompleteness_description",
    "_enforce_physics",
    "full_physics_report",
)

_PHYSICS_WELLS = ("I", "N", "P")
_PHYSICS_LATE_OPEN_STEP = 50


def _search_namespace() -> dict[str, object]:
    physics = pytest.importorskip(
        "backend.contexts.surrogate.domain.physics_checks",
        reason="физические проверки суррогата требуют torch (extras ml)",
    )
    module = _module_ast(SEARCH_SOURCE)
    wanted = set(_PHYSICS_FUNCTIONS)
    body = [
        node
        for node in module.body
        if (isinstance(node, ast.FunctionDef) and node.name in wanted)
        or (isinstance(node, ast.ClassDef) and node.name in _PHYSICS_CLASSES)
    ]
    found = {node.name for node in body}
    assert found == wanted | set(_PHYSICS_CLASSES), f"не найдено: {sorted((wanted | set(_PHYSICS_CLASSES)) - found)}"
    namespace: dict[str, object] = {
        "Invariant": physics.Invariant,
        "PhysicsReport": physics.PhysicsReport,
        "PhysicsCheckError": physics.PhysicsCheckError,
        "Severity": physics.Severity,
        "severity_of": physics.severity_of,
        "check_pair": physics.check_pair,
        "check_prediction": physics.check_prediction,
        "Mapping": Mapping,
        "Sequence": Sequence,
        "Schedule": Schedule,
        "RawModelOutput": physics.RawModelOutput,
        "ScheduleSearchError": ValueError,
        "SearchEnvironment": object,
        "_DIFFERENTIAL_INVARIANT_NAMES": (
            physics.Invariant.INJECTION_RESPONSE.value,
            physics.Invariant.MATERIAL_BALANCE.value,
        ),
    }
    exec(
        compile(ast.Module(body=body, type_ignores=[]), str(SEARCH_SOURCE), "exec"),
        namespace,
    )
    return namespace


def _physics_schedule(
    *, injector_setpoint: float = 15.0, producer_setpoint: float = 10.0
) -> Schedule:
    return Schedule(
        meta=ScheduleMeta(wells=_PHYSICS_WELLS, provenance="test"),
        initial_state={
            "I": WellState(
                Availability.AVAILABLE, Role.INJ, OperatingStatus.OPEN, injector_setpoint
            ),
            "N": WellState(
                Availability.NOT_COMMISSIONED, Role.NONE, OperatingStatus.SHUT, 0.0
            ),
            "P": WellState(
                Availability.AVAILABLE, Role.PROD, OperatingStatus.OPEN, producer_setpoint
            ),
        },
        fixed_deck_events=(
            FixedDeckEvent(
                control_step=0,
                well="P",
                operator="WCONPROD",
                raw_args=(
                    "OPEN", "LRAT", "1*", "1*", "1*", "10.0", "1*", "50", "1*", "1*",
                ),
            ),
            FixedDeckEvent(
                control_step=0,
                well="I",
                operator="WCONINJE",
                raw_args=("WATER", "OPEN", "RATE", "15.0", "1*", "300", "1*", "1*"),
            ),
        ),
        control_events=(
            ControlEvent(_PHYSICS_LATE_OPEN_STEP, "N", EventKind.SET_LRAT, value=5.0),
            ControlEvent(_PHYSICS_LATE_OPEN_STEP, "N", EventKind.OPEN),
            ControlEvent(10, "I", EventKind.SET_RATE, value=injector_setpoint),
            ControlEvent(10, "P", EventKind.SET_LRAT, value=producer_setpoint),
        ),
    )


def _physics_node(well: str, step: int, **overrides):
    raw_module = pytest.importorskip("backend.contexts.surrogate.domain.raw_model_output")
    commissioned = well != "N" or step >= _PHYSICS_LATE_OPEN_STEP
    values: dict[str, object] = {"well": well, "control_step": step}
    if not commissioned:
        values.update(
            oil_mass_delta=0.0,
            liquid_volume_delta=0.0,
            injection_volume_delta=0.0,
            liquid_rate=0.0,
            injection_rate=0.0,
            bhp=120.0,
        )
    elif well == "I":
        values.update(
            oil_mass_delta=0.0,
            liquid_volume_delta=0.0,
            injection_volume_delta=450.0,
            liquid_rate=0.0,
            injection_rate=15.0,
            bhp=250.0,
        )
    else:
        values.update(
            oil_mass_delta=5.0,
            liquid_volume_delta=20.0,
            injection_volume_delta=0.0,
            liquid_rate=10.0,
            injection_rate=0.0,
            bhp=80.0,
        )
    values.update(overrides)
    return raw_module.RawWellStepPrediction(**values)


def _physics_raw(schedule: Schedule, overrides=None):
    raw_module = pytest.importorskip("backend.contexts.surrogate.domain.raw_model_output")
    overrides = overrides or {}
    nodes = tuple(
        overrides.get((well, step), _physics_node(well, step))
        for well in _PHYSICS_WELLS
        for step in range(N_INTERVALS)
    )
    return raw_module.RawModelOutput(
        canonical_schedule_hash=hash_schedule(schedule),
        wells=_PHYSICS_WELLS,
        nodes=nodes,
    )


def _physics_lambda() -> Lambda:
    return Lambda(
        window_start=date(2007, 1, 1),
        window_end=date(2025, 9, 1),
        producers=("N", "P"),
        injectors=("I",),
        matrix=((0.2,), (0.5,)),
        lag_months=0,
        amplitude=1.0,
        stability=1.0,
        rank=1,
        condition_number=1.0,
        achievability_ok={"I": True},
    )


class _Env:
    def __init__(
        self,
        reference_schedule: Schedule | None,
        reference_response: object | None,
        lambda_: Lambda,
        provenance: Mapping[str, str],
    ) -> None:
        self.reference_schedule = reference_schedule
        self.reference_response = reference_response
        self.lambda_ = lambda_
        self.oil_density_t_per_m3 = 0.9131
        self.provenance = provenance


def _differential_names(physics) -> tuple[str, str]:
    return (
        physics.Invariant.INJECTION_RESPONSE.value,
        physics.Invariant.MATERIAL_BALANCE.value,
    )


def test_evaluator_calls_check_pair_not_check_prediction_alone() -> None:
    module = _module_ast(SEARCH_SOURCE)
    evaluator_source = ast.unparse(_function_def(module, "make_evaluator"))
    report_source = ast.unparse(_function_def(module, "full_physics_report"))

    assert "full_physics_report(env, schedule, scored.output)" in evaluator_source
    assert "check_prediction" not in evaluator_source
    assert "check_pair(" in report_source
    assert "check_prediction(" in report_source


def test_incomplete_report_is_not_admitted_even_without_blocking_flags() -> None:
    namespace = _search_namespace()
    physics = pytest.importorskip("backend.contexts.surrogate.domain.physics_checks")
    differential = _differential_names(physics)
    single_only = tuple(
        invariant
        for invariant in physics.Invariant
        if invariant.value not in differential
    )
    report = physics.PhysicsReport(
        counts={},
        examples=(),
        evaluated=single_only,
        skipped={name: "опоры нет" for name in differential},
        n_nodes=1,
        n_wells=1,
    )

    assert report.blocking_count == 0
    assert report.complete is False
    with pytest.raises(namespace["PhysicallyImpossibleScheduleError"]) as error:
        namespace["_enforce_physics"](report, True)

    assert error.value.missing_invariants == differential
    assert all(name in error.value.description for name in differential)
    assert "physics_complete=false" in error.value.description


def test_complete_clean_report_is_admitted() -> None:
    namespace = _search_namespace()
    physics = pytest.importorskip("backend.contexts.surrogate.domain.physics_checks")
    report = physics.PhysicsReport(
        counts={},
        examples=(),
        evaluated=tuple(physics.Invariant),
        skipped={},
        n_nodes=1,
        n_wells=1,
    )

    assert report.admissible is True
    namespace["_enforce_physics"](report, True)


def test_blocking_flag_on_a_complete_report_names_completeness() -> None:
    namespace = _search_namespace()
    physics = pytest.importorskip("backend.contexts.surrogate.domain.physics_checks")
    report = physics.PhysicsReport(
        counts={physics.Invariant.SHUT_WELL_FLOW.value: 3},
        examples=(),
        evaluated=tuple(physics.Invariant),
        skipped={},
        n_nodes=1,
        n_wells=1,
    )

    with pytest.raises(namespace["PhysicallyImpossibleScheduleError"]) as error:
        namespace["_enforce_physics"](report, True)

    assert "physics_complete=true" in error.value.description
    assert error.value.counts == {physics.Invariant.SHUT_WELL_FLOW.value: 3}
    assert error.value.missing_invariants == ()


def test_absent_anchor_rejects_the_candidate_with_a_named_reason() -> None:
    namespace = _search_namespace()
    physics = pytest.importorskip("backend.contexts.surrogate.domain.physics_checks")
    schedule = _physics_schedule(injector_setpoint=16.0)
    env = _Env(
        None,
        None,
        _physics_lambda(),
        {"reference": "absent: прогноз суррогата на опоре не построен: чекпойнт"},
    )

    with pytest.raises(namespace["MissingReferenceError"]) as error:
        namespace["full_physics_report"](env, schedule, _physics_raw(schedule))

    assert "опора недоступна" in error.value.description
    assert "absent:" in error.value.description
    assert error.value.missing_invariants == _differential_names(physics)


def test_absent_anchor_is_never_silently_downgraded_to_check_prediction() -> None:
    source = ast.unparse(_function_def(_module_ast(SEARCH_SOURCE), "full_physics_report"))
    guard = source.split("MissingReferenceError")[0]

    assert "check_prediction" not in guard
    assert "reference_schedule is None" in guard


def test_working_path_with_an_anchor_yields_a_complete_report() -> None:
    namespace = _search_namespace()
    physics = pytest.importorskip("backend.contexts.surrogate.domain.physics_checks")
    reference_schedule = _physics_schedule()
    candidate_schedule = _physics_schedule(injector_setpoint=16.0)
    env = _Env(
        reference_schedule,
        _physics_raw(reference_schedule),
        _physics_lambda(),
        {"reference": "base-case-schedule+surrogate-prediction"},
    )

    report = namespace["full_physics_report"](
        env, candidate_schedule, _physics_raw(candidate_schedule)
    )

    assert report.complete is True
    assert set(report.evaluated) == set(physics.Invariant)
    assert report.skipped == {}
    assert report.as_dict()["complete"] is True
    assert report.as_dict()["admissible"] is True
    namespace["_enforce_physics"](report, True)


def test_unusable_pair_is_rejected_and_never_crashes_the_search() -> None:
    namespace = _search_namespace()
    schedule = _physics_schedule()
    env = _Env(
        schedule,
        _physics_raw(schedule),
        _physics_lambda(),
        {"reference": "base-case-schedule+surrogate-prediction"},
    )

    with pytest.raises(namespace["MissingReferenceError"]) as error:
        namespace["full_physics_report"](env, schedule, _physics_raw(schedule))

    assert "непригодна" in error.value.description
