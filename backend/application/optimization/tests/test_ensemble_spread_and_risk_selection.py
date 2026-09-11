from __future__ import annotations

import ast
from dataclasses import dataclass, replace
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from backend.contexts.constraints.application.cases import load_case
from backend.contexts.optimization.infrastructure.artifacts import resolve_runtime_artifacts
from backend.contexts.optimization.application.environment import (
    EnsembleSpreadError,
    ensemble_members,
    ensemble_npv_sigma,
    load_environment,
    make_evaluator,
    spread_bracket,
)
from backend.contexts.optimization.application.search_use_case import (
    MISSING_SIGMA,
    SearchRunError,
    select_finalist,
)
from backend.core.contracts import EventKind, N_INTERVALS
from backend.contexts.schedule.domain.canonical import canonicalize
from backend.shared.resources import chdd_python_dir, model_z_dir
from backend.contexts.surrogate.application.ensemble import TrajectoryEnsemble
from backend.contexts.surrogate.domain.raw_model_output import (
    RawModelOutput,
    RawWellStepPrediction,
)
from backend.contexts.optimization.application import environment as _environment
from backend.contexts.optimization.application import search_use_case as _search_use_case

SEARCH_SOURCE = Path(_environment.__file__)
RUN_SOURCE = Path(_search_use_case.__file__)
RESPONSE = Path("data/base_case/response.json")
LAMBDA = Path("data/lambda-window-2007/lambda.json")
CONSTRAINTS = Path("config/competition-constraints.json")


@dataclass(frozen=True, slots=True)
class _Final:
    self_consistent: bool


def _finalist(
    npv: float, sigma: float | None, self_consistent: bool = True
) -> tuple[Any, ...]:
    return (
        npv,
        SimpleNamespace(values={}),
        object(),
        _Final(self_consistent),
        SimpleNamespace(violations=()),
        (),
        f"hash-{npv}-{sigma}",
        sigma,
    )


def _node(step: int, oil: float) -> RawWellStepPrediction:
    return RawWellStepPrediction(
        well="W1",
        control_step=step,
        oil_mass_delta=oil,
        liquid_volume_delta=oil * 2.0,
        injection_volume_delta=oil,
        liquid_rate=oil,
        injection_rate=oil,
        bhp=100.0,
    )


def _output(oil: float) -> RawModelOutput:
    return RawModelOutput(
        canonical_schedule_hash="h",
        wells=("W1",),
        nodes=tuple(_node(step, oil) for step in range(N_INTERVALS)),
    )


@pytest.fixture(scope="module")
def environment() -> Any:
    artifacts = resolve_runtime_artifacts()
    return load_environment(
        model_dir=model_z_dir(),
        normatives_path=chdd_python_dir() / "input" / "Нормативы_ЧДД.xlsx",
        response_path=RESPONSE,
        checkpoint_path=artifacts.checkpoint,
        feature_context_path=artifacts.feature_context,
        npv_head_path=artifacts.npv_head,
        npv_calibration_path=artifacts.npv_calibration,
        scenario_ood_path=artifacts.scenario_ood,
        lambda_path=LAMBDA,
        constraints=load_case(CONSTRAINTS),
        ood_threshold=1.0e9,
    )


@pytest.fixture(scope="module")
def candidate(environment: Any) -> Any:
    base = environment.base_schedule
    events = tuple(
        replace(event, value=float(event.value) - 1.0)
        if event.kind is EventKind.SET_LRAT and event.value and event.value > 2.0
        else event
        for event in base.control_events
    )
    return canonicalize(replace(base, control_events=events))


@pytest.fixture(scope="module")
def open_environment(environment: Any) -> Any:
    return replace(environment, physics_gate=False)


def test_ensemble_members_are_reachable_without_editing_the_ensemble(
    environment: Any,
) -> None:
    assert isinstance(environment.model, TrajectoryEnsemble)
    members = ensemble_members(environment.model)

    assert len(members) == len(environment.model.weights)
    assert len(members) >= 2


def test_sigma_is_computed_on_an_ensemble_and_is_not_zero(
    open_environment: Any, candidate: Any
) -> None:
    evaluated = make_evaluator(open_environment, with_sigma=True)(candidate)

    assert evaluated.sigma is not None
    assert evaluated.sigma > 0.0


def test_sigma_is_none_for_a_single_model_not_zero(
    open_environment: Any, candidate: Any
) -> None:
    member = ensemble_members(open_environment.model)[0]
    single = replace(open_environment, model=member)
    evaluated = make_evaluator(single, with_sigma=True)(candidate)

    assert evaluated.sigma is None


def test_sigma_costs_two_extra_economics_passes_and_none_in_the_hot_loop(
    open_environment: Any, candidate: Any
) -> None:
    import backend.contexts.optimization.application.environment as module

    calls = {"n": 0}
    original = module.predict_economics

    def counted(*args: Any, **kwargs: Any) -> Any:
        calls["n"] += 1
        return original(*args, **kwargs)

    module.predict_economics = counted  # type: ignore[assignment]
    try:
        make_evaluator(open_environment)(candidate)
        hot = calls["n"]
        calls["n"] = 0
        make_evaluator(open_environment, with_sigma=True)(candidate)
        final = calls["n"]
    finally:
        module.predict_economics = original  # type: ignore[assignment]

    assert hot == 1
    assert final == 3


def test_sigma_does_not_move_the_reported_npv(
    open_environment: Any, candidate: Any
) -> None:
    plain = make_evaluator(open_environment)(candidate)
    spread = make_evaluator(open_environment, with_sigma=True)(candidate)

    assert plain.sigma is None
    assert spread.npv == plain.npv


def test_spread_bracket_orders_members_by_total_oil() -> None:
    low, high = spread_bracket((_output(2.0), _output(5.0), _output(1.0)))

    assert low.nodes[0].oil_mass_delta == 1.0
    assert high.nodes[0].oil_mass_delta == 5.0


def test_spread_bracket_refuses_a_single_member() -> None:
    with pytest.raises(EnsembleSpreadError):
        spread_bracket((_output(1.0),))


def test_sigma_is_none_for_a_non_ensemble_model_object() -> None:
    env = SimpleNamespace(model=SimpleNamespace(version="v"))

    assert ensemble_npv_sigma(env, object(), object(), object()) is None


def test_beta_zero_selects_exactly_as_the_previous_key_did() -> None:
    finalists = [
        _finalist(10.0, 1.0, self_consistent=False),
        _finalist(9.0, 5.0, self_consistent=True),
        _finalist(8.0, 0.0, self_consistent=True),
        _finalist(20.0, 9.0, self_consistent=False),
    ]
    previous = max(finalists, key=lambda item: (item[3].self_consistent, item[0]))

    assert select_finalist(finalists, 0.0) is previous


def test_beta_zero_ignores_missing_sigma_entirely() -> None:
    finalists = [_finalist(10.0, None), _finalist(12.0, None)]

    assert select_finalist(finalists, 0.0)[0] == 12.0


def test_positive_beta_without_sigma_is_an_explicit_error() -> None:
    finalists = [_finalist(10.0, 1.0), _finalist(12.0, None)]

    with pytest.raises(SearchRunError) as error:
        select_finalist(finalists, 0.5)

    assert str(error.value) == MISSING_SIGMA
    assert "ансамбль" in str(error.value)


def test_positive_beta_prefers_the_narrower_spread_at_equal_npv() -> None:
    wide = _finalist(10.0, 4.0)
    narrow = _finalist(10.0, 1.0)

    assert select_finalist([wide, narrow], 1.0) is narrow
    assert select_finalist([narrow, wide], 1.0) is narrow


def test_positive_beta_still_lets_money_win_when_it_covers_the_spread() -> None:
    risky = _finalist(100.0, 10.0)
    safe = _finalist(50.0, 0.0)

    assert select_finalist([risky, safe], 1.0) is risky


def test_self_consistency_still_dominates_money_under_positive_beta() -> None:
    consistent = _finalist(1.0, 100.0, self_consistent=True)
    richer = _finalist(1000.0, 0.0, self_consistent=False)

    assert select_finalist([consistent, richer], 2.0) is consistent


def test_negative_beta_is_refused() -> None:
    with pytest.raises(SearchRunError):
        select_finalist([_finalist(1.0, 1.0)], -0.1)


def test_empty_finalist_set_is_refused() -> None:
    with pytest.raises(SearchRunError):
        select_finalist([], 0.0)


def _module_ast(path: Path) -> ast.Module:
    return ast.parse(path.read_text(encoding="utf-8"))


def _function_def(module: ast.Module, name: str) -> ast.FunctionDef:
    return next(
        node
        for node in ast.walk(module)
        if isinstance(node, ast.FunctionDef) and node.name == name
    )


def test_sigma_is_asked_for_only_on_the_final_recompute() -> None:
    source = ast.unparse(_function_def(_module_ast(RUN_SOURCE), "run_search"))

    assert "make_evaluator(env, with_sigma=True)" in source
    assert (
        "resolve(make_policy(env, theta, {}), evaluator, initial, search_cap)"
        in source
    )
    assert "select_finalist(finalists, RISK_AVERSION_BETA)" in source


def test_touched_sources_carry_no_comments_and_no_docstrings() -> None:
    for path in (SEARCH_SOURCE, RUN_SOURCE):
        module = _module_ast(path)
        assert ast.get_docstring(module) is None
        for node in ast.walk(module):
            if isinstance(
                node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)
            ):
                assert ast.get_docstring(node) is None, f"{path}:{node.name}"
