from __future__ import annotations

import ast
import io
import json
import math
import sys
import tokenize
import types
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType, SimpleNamespace
from typing import Any, Mapping, Sequence

import pytest
from backend.contexts.optimization.application import environment as _environment
from backend.contexts.optimization.application import finalist_selection as _finalist_selection
from backend.contexts.optimization.infrastructure import diagnostics_journal as _diagnostics_journal
from backend.contexts.optimization.application import search_use_case as _search_use_case
from backend.shared.json_io import read_json

RUN_SOURCE = Path(_search_use_case.__file__)
FINALIST_SOURCE = Path(_finalist_selection.__file__)
SEARCH_SOURCE = Path(_environment.__file__)
from backend.contexts.optimization.domain import errors as optimization_errors
from backend.contexts.optimization.domain import ood_penalty
from backend.contexts.optimization.domain import physics_gate

FIELD_NAMES = (
    "schedule_hash",
    "theta",
    "npv_predicted",
    "npv_parts",
    "ood_score",
    "ood_worst",
    "scenario_ood",
    "physics_counts",
    "physics_complete",
    "physics_admissible",
    "static_violations",
    "dynamic_blocking_violations",
    "feasible",
    "violations",
)


def _module_ast(path: Path) -> ast.Module:
    return ast.parse(path.read_text(encoding="utf-8"))


def _context_module_ast(path: Path) -> ast.Module:
    root = path.parent.parent
    body: list[ast.stmt] = []
    for source in sorted(root.rglob("*.py")):
        if "__pycache__" in source.parts:
            continue
        body.extend(ast.parse(source.read_text(encoding="utf-8")).body)
    return ast.Module(body=body, type_ignores=[])


def _context_source(path: Path) -> str:
    root = path.parent.parent
    return chr(10).join(
        source.read_text(encoding="utf-8")
        for source in sorted(root.rglob("*.py"))
        if "__pycache__" not in source.parts
    )


def _function_def(module: ast.Module, name: str) -> ast.FunctionDef:
    for node in module.body:
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return node
    raise AssertionError(f"function {name} not found")


def _run_namespace() -> dict[str, object]:
    namespace: dict[str, object] = dict(vars(_search_use_case))
    namespace.update(vars(_finalist_selection))
    namespace.update(vars(_diagnostics_journal))
    namespace.update(vars(optimization_errors))
    return namespace


def _search_namespace() -> dict[str, object]:
    namespace: dict[str, object] = dict(vars(ood_penalty))
    namespace.update(vars(physics_gate))
    return namespace


class _Exceedance:
    def __init__(self, feature: str, well: str, control_step: int) -> None:
        self.feature = feature
        self.well = well
        self.control_step = control_step
        self.value = 12.0
        self.low = 0.0
        self.high = 1.0
        self.score = 11.0


class _Ood:
    def __init__(self, worst: _Exceedance | None, score: float = 0.0) -> None:
        self.worst = worst
        self.score = score


class _Report:
    def __init__(
        self,
        counts: Mapping[str, int],
        *,
        complete: bool = True,
        admissible: bool = True,
        blocking: int = 0,
        warning: int = 0,
    ) -> None:
        self.counts = counts
        self.complete = complete
        self.admissible = admissible
        self.blocking_count = blocking
        self.warning_count = warning


def test_ood_worst_is_a_short_string_of_the_required_shape() -> None:
    namespace = _search_namespace()

    text = namespace["format_ood_worst"](
        _Ood(_Exceedance("setpoint_m3_per_day", "P17", 42))
    )

    assert text == "setpoint_m3_per_day@P17:42"
    assert isinstance(text, str)


def test_ood_worst_is_none_when_nothing_exceeded() -> None:
    namespace = _search_namespace()

    assert namespace["format_ood_worst"](_Ood(None)) is None


def test_physics_counters_carry_flags_completeness_and_admissibility() -> None:
    namespace = _search_namespace()

    counters = namespace["physics_counters"](
        _Report(
            {"material_balance": 3, "injection_response": 1},
            complete=True,
            admissible=False,
            blocking=3,
            warning=1,
        )
    )

    assert counters["material_balance"] == 3
    assert counters["injection_response"] == 1
    assert counters["blocking_count"] == 3
    assert counters["warning_count"] == 1
    assert counters["complete"] == 1
    assert counters["admissible"] == 0


def test_make_evaluator_fills_every_new_evaluation_field() -> None:
    source = ast.unparse(_function_def(_context_module_ast(SEARCH_SOURCE), "make_evaluator"))

    assert "npv_parts=" in source
    assert "physics=MappingProxyType(physics_counters(physics))" in source
    assert "ood_worst=format_ood_worst(scored.ood)" in source
    assert "sigma=" in source
    assert 'npv_parts = predict_economics(env, model_input, response)' in source
    assert 'npv = npv_parts[\'blended\']' in source


def test_evaluation_construction_names_all_four_fields() -> None:
    module = _context_module_ast(SEARCH_SOURCE)
    evaluator = _function_def(module, "make_evaluator")
    call = next(
        node
        for node in ast.walk(evaluator)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "Evaluation"
    )
    keywords = {keyword.arg for keyword in call.keywords}

    assert {"npv_parts", "sigma", "physics", "ood_worst"} <= keywords


def test_candidate_card_contains_every_diagnostic_field() -> None:
    namespace = _run_namespace()

    card = namespace["candidate_card"](
        schedule_hash="abc123",
        theta={"r5_compensation_low": 0.8},
        npv_predicted=1.5e10,
        npv_parts={"direct": 1.0, "physical": 2.0, "blended": 1.5},
        ood_score=0.25,
        ood_worst="setpoint_m3_per_day@P17:42",
        scenario_ood=0.9,
        physics={"material_balance": 2, "complete": 1, "admissible": 0},
        static_violations=3,
        dynamic_blocking_violations=4,
        feasible=False,
        violations=[{"scenario_id": "static-contract", "regret": 3.0, "what": "x"}],
        strategy="cma-es",
    )

    for name in FIELD_NAMES:
        assert name in card, name
    assert card["schedule_hash"] == "abc123"
    assert card["ood_score"] == 0.25
    assert card["ood_worst"] == "setpoint_m3_per_day@P17:42"
    assert card["scenario_ood"] == 0.9
    assert card["npv_parts"] == {"blended": 1.5, "direct": 1.0, "physical": 2.0}
    assert card["physics_counts"]["material_balance"] == 2
    assert card["physics_complete"] is True
    assert card["physics_admissible"] is False
    assert card["static_violations"] == 3
    assert card["dynamic_blocking_violations"] == 4
    assert card["strategy"] == "cma-es"
    json.dumps(card, ensure_ascii=False, allow_nan=False)


def test_candidate_card_survives_a_candidate_that_was_never_scored() -> None:
    namespace = _run_namespace()

    card = namespace["candidate_card"](
        schedule_hash="",
        theta={},
        npv_predicted=None,
        npv_parts={},
        ood_score=None,
        ood_worst=None,
        scenario_ood=None,
        physics={},
        static_violations=None,
        dynamic_blocking_violations=None,
        feasible=False,
        violations=[],
        strategy="cma-es",
    )

    assert card["npv_predicted"] is None
    assert card["ood_worst"] is None
    assert card["physics_admissible"] is False
    assert card["physics_complete"] is False


@pytest.mark.parametrize(
    "kwargs",
    [
        {"static_violations": 1},
        {"dynamic_blocking_violations": 1},
        {"physics_admissible": False},
        {"ood_score": None},
        {"ood_score": 0.5},
    ],
)
def test_a_candidate_that_failed_a_check_never_becomes_incumbent(
    kwargs: dict[str, Any],
) -> None:
    namespace = _run_namespace()
    passing = {
        "static_violations": 0,
        "dynamic_blocking_violations": 0,
        "ood_score": 0.0,
        "ood_threshold": 0.0,
        "physics_admissible": True,
    }

    assert namespace["incumbent_gate_passed"](**passing) is True
    assert namespace["incumbent_gate_passed"](**{**passing, **kwargs}) is False


def test_the_gate_scores_the_repaired_candidate_not_the_pre_repair_one() -> None:
    source = ast.unparse(
        _function_def(_context_module_ast(FINALIST_SOURCE), "evaluate_finalists")
    )

    assert "incumbent_gate_passed(" in source
    assert "ood_score=evaluated.ood_score" in source
    assert "physics_admissible=admissible" in source
    assert "admissible = _physics_admissible(evaluated.physics)" in source
    assert "final.ood_score <= env.ood_threshold" not in source


def test_only_a_gated_candidate_reaches_the_finalist_list() -> None:
    module = _context_module_ast(FINALIST_SOURCE)
    run_search = _function_def(module, "evaluate_finalists")
    guarded = next(
        node
        for node in ast.walk(run_search)
        if isinstance(node, ast.If)
        and isinstance(node.test, ast.Name)
        and node.test.id == "passed"
    )
    body = ast.unparse(guarded)

    assert "finalists.append" in body
    assert "registry.promote" in body


def test_the_registry_records_hash_npv_and_order() -> None:
    namespace = _run_namespace()
    registry = namespace["IncumbentRegistry"]()

    assert registry.current is None

    first = registry.promote(
        stage="finalist",
        schedule_hash="hash-one",
        npv_predicted=1.0e10,
        theta={"a": 1.0},
        ood_score=0.0,
        ood_worst=None,
        static_violations=0,
        dynamic_blocking_violations=0,
        physics_admissible=True,
        self_consistent=False,
    )
    second = registry.promote(
        stage="finalist",
        schedule_hash="hash-two",
        npv_predicted=1.2e10,
        theta={"a": 2.0},
        ood_score=0.0,
        ood_worst="setpoint_m3_per_day@P1:0",
        static_violations=0,
        dynamic_blocking_violations=0,
        physics_admissible=True,
        self_consistent=True,
    )

    assert first.sequence == 0
    assert second.sequence == 1
    assert registry.current is second
    assert [record.schedule_hash for record in registry.records] == [
        "hash-one",
        "hash-two",
    ]

    dumped = registry.as_list()
    assert [item["schedule_hash"] for item in dumped] == ["hash-one", "hash-two"]
    assert dumped[1]["npv_predicted"] == 1.2e10
    assert dumped[1]["self_consistent"] is True
    assert dumped[0]["theta"] == {"a": 1.0}
    json.dumps(dumped, ensure_ascii=False, allow_nan=False)


def test_the_registry_is_written_beside_the_diagnostics(tmp_path: Path) -> None:
    namespace = _run_namespace()
    path = tmp_path / "cmaes-diagnostics.json"
    path.write_text(
        json.dumps({"seed": 1, "evaluations": []}, ensure_ascii=False),
        encoding="utf-8",
    )
    registry = namespace["IncumbentRegistry"]()
    registry.promote(
        stage="finalist",
        schedule_hash="hash-one",
        npv_predicted=1.0e10,
        theta={},
        ood_score=0.0,
        ood_worst=None,
        static_violations=0,
        dynamic_blocking_violations=0,
        physics_admissible=True,
        self_consistent=True,
    )

    namespace["_write_diagnostics_tail"]([{"strategy": "finalist"}], registry, path)

    written = json.loads(path.read_text(encoding="utf-8"))
    assert written["incumbents"][0]["schedule_hash"] == "hash-one"
    assert written["finalists"] == [{"strategy": "finalist"}]
    assert written["seed"] == 1


def test_a_missing_diagnostics_file_is_an_error_not_a_silent_skip(
    tmp_path: Path,
) -> None:
    namespace = _run_namespace()
    namespace["SEARCH_DIAGNOSTICS"] = tmp_path / "absent.json"

    with pytest.raises(namespace["SearchRunError"], match="search diagnostics"):
        namespace["_write_diagnostics_tail"]([], namespace["IncumbentRegistry"]())


def test_diagnostics_join_refuses_to_guess_when_cards_are_missing() -> None:
    namespace = _run_namespace()
    history = (
        SimpleNamespace(
            theta=SimpleNamespace(values={"a": 1.0}),
            result=SimpleNamespace(
                objective=1.0, feasible=True, violations_by_scenario=()
            ),
        ),
    )

    with pytest.raises(namespace["SearchRunError"], match="out of sync"):
        namespace["_evaluation_cards"](history, [])


def test_diagnostics_join_keeps_every_card_field() -> None:
    namespace = _run_namespace()
    card = namespace["candidate_card"](
        schedule_hash="abc",
        theta={"a": 1.0},
        npv_predicted=5.0,
        npv_parts={"blended": 5.0},
        ood_score=0.0,
        ood_worst=None,
        scenario_ood=0.5,
        physics={"complete": 1, "admissible": 1},
        static_violations=0,
        dynamic_blocking_violations=0,
        feasible=True,
        violations=[],
        strategy="cma-es",
    )
    history = (
        SimpleNamespace(
            theta=SimpleNamespace(values={"a": 1.0}),
            result=SimpleNamespace(
                objective=5.0, feasible=True, violations_by_scenario=()
            ),
        ),
    )

    merged = namespace["_evaluation_cards"](history, [card])

    assert len(merged) == 1
    for name in FIELD_NAMES:
        assert name in merged[0], name
    assert merged[0]["npv_predicted"] == 5.0
    assert merged[0]["schedule_hash"] == "abc"
    assert merged[0]["scenario_ood"] == 0.5


def test_an_infinite_objective_lands_as_null_not_as_nan() -> None:
    namespace = _run_namespace()
    card = namespace["candidate_card"](
        schedule_hash="",
        theta={},
        npv_predicted=None,
        npv_parts={},
        ood_score=None,
        ood_worst=None,
        scenario_ood=None,
        physics={},
        static_violations=None,
        dynamic_blocking_violations=None,
        feasible=False,
        violations=[],
        strategy="cma-es",
    )
    history = (
        SimpleNamespace(
            theta=SimpleNamespace(values={}),
            result=SimpleNamespace(
                objective=-math.inf, feasible=False, violations_by_scenario=()
            ),
        ),
    )

    merged = namespace["_evaluation_cards"](history, [card])

    assert merged[0]["npv_predicted"] is None
    json.dumps(merged, ensure_ascii=False, allow_nan=False)


def test_the_fallback_also_gates_on_physics_and_writes_the_registry() -> None:
    source = ast.unparse(
        _function_def(_context_module_ast(RUN_SOURCE), "_search_near_baseline")
    )

    assert "_physics_admissible(physics)" in source
    assert "surrogate-physics" in source
    assert "registry.promote(" in source
    assert "diagnostics['incumbents'] = registry.as_list()" in source
    assert "candidate_card(" in source


def test_the_outcome_carries_the_incumbent_history_to_the_written_result() -> None:
    module = _context_module_ast(RUN_SOURCE)
    run_search = ast.unparse(_function_def(module, "run_search"))
    main = ast.unparse(_function_def(module, "main"))

    assert "incumbent_history=registry.records" in run_search
    assert "incumbents" in main
    assert "outcome.incumbent_history" in main


@pytest.mark.parametrize("path", [RUN_SOURCE, SEARCH_SOURCE])
def test_the_touched_modules_carry_no_comments(path: Path) -> None:
    source = path.read_text(encoding="utf-8")
    allowed = ("# type: ignore", "# noqa", "# pragma: no cover")
    for token in tokenize.generate_tokens(io.StringIO(source).readline):
        if token.type == tokenize.COMMENT:
            assert token.string.startswith(allowed), token.string
    tree = ast.parse(source)
    assert ast.get_docstring(tree) is None
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            assert ast.get_docstring(node) is None, node.name


def test_mapping_proxy_keeps_the_evaluation_fields_immutable() -> None:
    namespace = _search_namespace()
    counters = MappingProxyType(
        namespace["physics_counters"](_Report({"material_balance": 1}))
    )

    with pytest.raises(TypeError):
        counters["material_balance"] = 2
