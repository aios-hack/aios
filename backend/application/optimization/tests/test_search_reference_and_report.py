from __future__ import annotations

import ast
import inspect
import json
from dataclasses import dataclass, fields
from pathlib import Path
from types import SimpleNamespace

import pytest

from backend.core.contracts import (
    Availability,
    canonical_bytes,
    OperatingStatus,
    Role,
    Schedule,
    ScheduleMeta,
    Theta,
    WellState,
)

SEARCH_SOURCE = (
    Path(__file__).resolve().parents[1] / "schedule_search.py"
)
RUN_SOURCE = (
    Path(__file__).resolve().parents[1] / "search_run.py"
)


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
        "backend.ml.surrogate.physics_checks",
        reason="физические проверки суррогата требуют torch (extras ml)",
    )
    search = pytest.importorskip(
        "backend.application.optimization.schedule_search",
        reason="сквозной поиск требует torch (extras ml)",
    )
    signature = inspect.signature(physics.check_pair)
    hints = {
        name: parameter.annotation
        for name, parameter in signature.parameters.items()
    }
    assert hints["reference"] is physics.RawModelOutput
    assert hints["reference_schedule"] is Schedule

    field_types = {item.name: item.type for item in fields(search.SearchEnvironment)}
    assert field_types["reference_response"] == "RawModelOutput | None"
    assert field_types["reference_schedule"] == "Schedule | None"


def test_missing_anchor_is_none_and_marked_in_provenance() -> None:
    search = pytest.importorskip(
        "backend.application.optimization.schedule_search",
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
        "BASE_NPV": 11_873_676_459.64,
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
