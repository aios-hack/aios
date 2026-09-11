from __future__ import annotations

import ast
import hashlib
import importlib
import importlib.abc
import importlib.machinery
import importlib
import io
import json
import math
import os
import random
import sys
import time
import tokenize
import types
from pathlib import Path
from dataclasses import dataclass, replace
from backend.contexts.constraints.domain.constraints import Constraints
from backend.shared.hashing import canonical_bytes
from types import SimpleNamespace
from typing import Any, Iterator, Mapping, Sequence

import pytest

from backend.contexts.optimization.infrastructure.artifacts import (
    RuntimeArtifactError,
    RuntimeArtifacts,
    resolve_runtime_artifacts,
    validate_npv_scoring_is_unambiguous,
)
from backend.contexts.optimization.infrastructure import artifacts as _artifacts
from backend.contexts.optimization.application import environment as _environment
from backend.contexts.optimization.application import search_use_case as _search_use_case

RUN_SOURCE = Path(_search_use_case.__file__)
SEARCH_SOURCE = Path(_environment.__file__)
ARTIFACTS_SOURCE = Path(_artifacts.__file__)
from backend.contexts.optimization.application import economics_prediction
from backend.contexts.optimization.domain import errors as optimization_errors

TORCH_PACKAGES = (
    "torch",
    "torch.nn",
    "torch.nn.functional",
    "torch.nn.init",
    "torch.utils",
    "torch.utils.data",
    "torch.optim",
    "torch.linalg",
    "torch.cuda",
    "torch.autograd",
)


class _AnyObject:
    def __init__(self, *args: Any, **kwargs: Any) -> None:
        pass

    def __call__(self, *args: Any, **kwargs: Any) -> "_AnyObject":
        return _AnyObject()

    def __getattr__(self, name: str) -> Any:
        if name.startswith("__"):
            raise AttributeError(name)
        return _AnyObject()


class _StubModule(types.ModuleType):
    __path__: list[str] = []

    def __getattr__(self, name: str) -> Any:
        if name.startswith("__"):
            raise AttributeError(name)
        created = type(name, (_AnyObject,), {})
        setattr(self, name, created)
        return created


class _StubLoader(importlib.abc.Loader):
    def create_module(
        self, spec: importlib.machinery.ModuleSpec
    ) -> types.ModuleType:
        return _StubModule(spec.name)

    def exec_module(self, module: types.ModuleType) -> None:
        pass


class _StubFinder(importlib.abc.MetaPathFinder):
    def find_spec(
        self, name: str, path: Any = None, target: Any = None
    ) -> importlib.machinery.ModuleSpec | None:
        if name in TORCH_PACKAGES:
            return importlib.machinery.ModuleSpec(
                name, _StubLoader(), is_package=True
            )
        return None


def _install_torch_stub() -> list[str]:
    if "torch" in sys.modules:
        return []
    finder = _StubFinder()
    sys.meta_path.insert(0, finder)
    installed: list[str] = []
    try:
        for name in TORCH_PACKAGES:
            importlib.import_module(name)
            installed.append(name)
        for name in TORCH_PACKAGES[1:]:
            parent, _, leaf = name.rpartition(".")
            setattr(sys.modules[parent], leaf, sys.modules[name])
    finally:
        sys.meta_path.remove(finder)
    return installed


def _drop_stubbed(stubbed: list[str]) -> None:
    if not stubbed:
        return
    for name in [
        module
        for module in sys.modules
        if module.startswith("backend.contexts.surrogate")
        or module.startswith("backend.contexts.optimization.application.environment")
        or module.startswith("backend.contexts.optimization.application.search_use_case")
    ]:
        sys.modules.pop(name, None)
    for name in reversed(stubbed):
        sys.modules.pop(name, None)


def _load_module(dotted: str) -> Any:
    stubbed: list[str] = []
    try:
        import torch  # noqa: F401
    except ImportError:
        stubbed = _install_torch_stub()
    try:
        return importlib.import_module(dotted)
    finally:
        _drop_stubbed(stubbed)


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


def _reload_search_run(environ: dict[str, str]) -> Any:
    saved = {name: os.environ.get(name) for name in environ}
    os.environ.update(environ)
    try:
        sys.modules.pop("backend.contexts.optimization.application.search_config", None)
        sys.modules.pop("backend.contexts.optimization.application.search_use_case", None)
        return _load_module("backend.contexts.optimization.application.search_use_case")
    finally:
        for name, value in saved.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value
        sys.modules.pop("backend.contexts.optimization.application.search_config", None)
        sys.modules.pop("backend.contexts.optimization.application.search_use_case", None)


@pytest.fixture
def artifact_tree(tmp_path: Path) -> Iterator[Path]:
    for name in ("trajectory.json", "context.json", "head.pt", "calibration.json"):
        (tmp_path / name).write_bytes(b"artifact")
    yield tmp_path


def test_calibration_beside_a_head_is_refused_when_artifacts_resolve(
    artifact_tree: Path,
) -> None:
    with pytest.raises(RuntimeArtifactError) as error:
        resolve_runtime_artifacts(
            {
                "AIOS_CHECKPOINT_PATH": str(artifact_tree / "trajectory.json"),
                "AIOS_FEATURE_CONTEXT_PATH": str(artifact_tree / "context.json"),
                "AIOS_NPV_HEAD_PATH": str(artifact_tree / "head.pt"),
                "AIOS_NPV_CALIBRATION_PATH": str(artifact_tree / "calibration.json"),
            }
        )
    message = str(error.value)
    assert "calibration" in message
    assert "direct forecast head" in message


def test_calibration_alone_resolves(artifact_tree: Path) -> None:
    (artifact_tree / "head.pt").unlink()
    result = resolve_runtime_artifacts(
        {
            "AIOS_CHECKPOINT_PATH": str(artifact_tree / "trajectory.json"),
            "AIOS_FEATURE_CONTEXT_PATH": str(artifact_tree / "context.json"),
            "AIOS_NPV_CALIBRATION_PATH": str(artifact_tree / "calibration.json"),
        }
    )

    assert result.npv_calibration == artifact_tree / "calibration.json"
    assert result.npv_head is None


def test_a_declared_calibration_that_is_absent_is_an_error_not_a_skip(
    tmp_path: Path,
) -> None:
    (tmp_path / "trajectory.json").write_bytes(b"artifact")
    (tmp_path / "context.json").write_bytes(b"artifact")
    with pytest.raises(RuntimeArtifactError, match="missing runtime artifact"):
        resolve_runtime_artifacts(
            {
                "AIOS_CHECKPOINT_PATH": str(tmp_path / "trajectory.json"),
                "AIOS_FEATURE_CONTEXT_PATH": str(tmp_path / "context.json"),
                "AIOS_NPV_CALIBRATION_PATH": str(tmp_path / "absent.json"),
            }
        )


def test_the_guard_is_a_named_function_anyone_can_call(tmp_path: Path) -> None:
    both = RuntimeArtifacts(
        checkpoint=tmp_path / "trajectory.json",
        feature_context=tmp_path / "context.json",
        npv_head=tmp_path / "head.pt",
        source="test",
        npv_calibration=tmp_path / "calibration.json",
    )
    with pytest.raises(RuntimeArtifactError):
        validate_npv_scoring_is_unambiguous(both)

    validate_npv_scoring_is_unambiguous(
        RuntimeArtifacts(
            checkpoint=tmp_path / "trajectory.json",
            feature_context=tmp_path / "context.json",
            npv_head=None,
            source="test",
            npv_calibration=tmp_path / "calibration.json",
        )
    )
    validate_npv_scoring_is_unambiguous(
        RuntimeArtifacts(
            checkpoint=tmp_path / "trajectory.json",
            feature_context=tmp_path / "context.json",
            npv_head=tmp_path / "head.pt",
            source="test",
            npv_calibration=None,
        )
    )


def _scoring_namespace(monkeypatch: pytest.MonkeyPatch) -> dict[str, object]:
    monkeypatch.setattr(
        economics_prediction,
        "analyze_base_case",
        lambda *args, **kwargs: SimpleNamespace(npv_methodology=100.0),
    )
    namespace: dict[str, object] = dict(vars(economics_prediction))
    namespace.update(vars(optimization_errors))
    return namespace


class _Calibration:
    def apply(self, raw: float) -> float:
        return 2.0 * float(raw) + 5.0


class _Head:
    physical_npv_weight = 0.25

    def predict(self, model_input: object) -> float:
        return 200.0


class _ScoringEnv:
    def __init__(self, head: object | None, calibration: object | None) -> None:
        self.npv_head = head
        self.npv_calibration = calibration
        self.deck_dates = ()
        self.t0_deck_date_index = 0
        self.normatives = None
        self.policies = None


def test_calibration_beside_a_head_is_never_silently_dropped_while_scoring(monkeypatch: pytest.MonkeyPatch) -> None:
    namespace = _scoring_namespace(monkeypatch)
    env = _ScoringEnv(_Head(), _Calibration())

    with pytest.raises(namespace["ScheduleSearchError"]) as error:
        namespace["predict_economics"](env, object(), object())

    assert "calibration" in str(error.value)


def test_calibration_without_a_head_still_shapes_the_number(monkeypatch: pytest.MonkeyPatch) -> None:
    namespace = _scoring_namespace(monkeypatch)
    env = _ScoringEnv(None, _Calibration())

    parts = namespace["predict_economics"](env, object(), object())

    assert parts["physical"] == 100.0
    assert parts["blended"] == 205.0


def test_a_head_without_a_calibration_blends_as_before(monkeypatch: pytest.MonkeyPatch) -> None:
    namespace = _scoring_namespace(monkeypatch)
    env = _ScoringEnv(_Head(), None)

    parts = namespace["predict_economics"](env, object(), object())

    assert parts["direct"] == 200.0
    assert parts["blended"] == pytest.approx(0.75 * 200.0 + 0.25 * 100.0)


def test_load_environment_refuses_the_pair_before_any_candidate_is_scored() -> None:
    source = ast.unparse(_function_def(_context_module_ast(SEARCH_SOURCE), "load_environment"))

    assert "npv_calibration_path" in source
    assert "_validate_npv_scoring_is_unambiguous(npv_head, npv_calibration)" in source
    assert "npv_calibration=npv_calibration" in source


def test_run_search_hands_the_calibration_to_the_environment() -> None:
    source = ast.unparse(_function_def(_context_module_ast(RUN_SOURCE), "run_search"))

    assert "npv_calibration_path=artifacts.npv_calibration" in source


def _run_path_source() -> str:
    module = _context_module_ast(RUN_SOURCE)
    parts = [ast.unparse(_function_def(module, "run_search"))]
    for dotted, name in (
        ("backend.contexts.optimization.application.search_provenance", "build_search_provenance"),
        ("backend.contexts.optimization.application.finalist_selection", "evaluate_finalists"),
    ):
        source = Path(importlib.import_module(dotted).__file__).read_text(encoding="utf-8")
        parts.append(ast.unparse(_function_def(ast.parse(source), name)))
    return chr(10).join(parts)


def test_both_return_paths_carry_the_strategy_and_the_equilibrium() -> None:
    module = _context_module_ast(RUN_SOURCE)
    run_search = _run_path_source()
    fallback = ast.unparse(_function_def(module, "_search_near_baseline"))

    assert "'search_strategy': 'cma-es'" in run_search
    assert "search_strategy='cma-es'" in run_search
    assert "policy_equilibrium" in run_search
    assert "search_strategy='lambda-connectivity-transfer'" in fallback
    assert "policy_equilibrium='not-claimed'" in fallback


def _provenance_from(path: str, tmp_path: Path) -> dict[str, str]:
    captured: dict[str, dict[str, str]] = {}
    diagnostics = tmp_path / "cmaes-diagnostics.json"
    diagnostics.write_text(
        json.dumps({"evaluations": []}, ensure_ascii=False), encoding="utf-8"
    )

    def _fallback(
        env: object,
        evaluator: object,
        budget: int,
        provenance: dict,
        registry: object | None = None,
    ) -> object:
        captured["seeded"] = dict(provenance)
        return _outcome_factory(
            None,
            None,
            0.0,
            "",
            dict(
                provenance,
                search_strategy="baseline-neighborhood",
                selected_candidate="baseline",
                policy_equilibrium="not-claimed",
            ),
            0,
            False,
            False,
            0,
            0,
        )

    context = tmp_path / "feature_context.json"
    context.write_bytes(b"feature-context")
    overrides = dict(_run_search_stubs(path, captured, feature_context=context))
    overrides["_search_near_baseline"] = _fallback
    overrides["SEARCH_DIAGNOSTICS"] = diagnostics
    overrides["print"] = lambda *args, **kwargs: None
    namespace = _run_search_module(overrides)
    outcome = namespace["run_search"]()
    return dict(outcome.provenance)


def _outcome_factory(*args: Any, **kwargs: Any) -> SimpleNamespace:
    names = (
        "schedule",
        "theta",
        "predicted_npv",
        "schedule_hash",
        "provenance",
        "evaluations",
        "converged",
        "self_consistent",
        "static_violations",
        "dynamic_blocking_violations",
    )
    values = dict(zip(names, args))
    values.update(kwargs)
    return SimpleNamespace(**values)


_RUN_SEARCH_TORCH_BACKED = (
    "SOURCE_WATER_BALANCE_REPAIR",
    "injection_budget_for_step",
    "load_environment",
    "make_evaluator",
    "make_policy",
    "OutOfDomainScheduleError",
    "PhysicallyImpossibleScheduleError",
)


def _run_search_import_namespace() -> dict[str, object]:
    namespace: dict[str, object] = dict(vars(_search_use_case))
    namespace.update({
        "hashlib": hashlib,
        "json": json,
        "math": math,
        "os": os,
        "random": random,
        "sys": SimpleNamespace(argv=["search_run"]),
        "time": time,
        "dataclass": dataclass,
        "replace": replace,
        "Path": Path,
        "Mapping": Mapping,
        "Sequence": Sequence,
    })
    for dotted, names in _RUN_SEARCH_IMPORT_SOURCES:
        module = importlib.import_module(dotted)
        for name in names:
            namespace[name] = getattr(module, name)
    for name in _RUN_SEARCH_TORCH_BACKED:
        namespace.setdefault(name, _AnyObject)
    return namespace


_RUN_SEARCH_IMPORT_SOURCES: tuple[tuple[str, tuple[str, ...]], ...] = (
    (
        "backend.contexts.policy.domain.policy",
        ("OptimizerResult", "ScenarioViolation", "Theta"),
    ),
    (
        "backend.contexts.schedule.domain.schedule",
        ("EventKind", "Schedule"),
    ),
    (
        "backend.contexts.constraints.domain.constraints",
        ("compensation_policy", "water_supply_policy"),
    ),
    ("backend.shared.hashing", ("canonical_bytes", "hash_schedule")),
    ("backend.contexts.schedule.domain.schedule", ("MAX_LRAT_M3_PER_DAY",)),
    (
        "backend.contexts.economics.application.base_case",
        ("load_response_artifact",),
    ),
    (
        "backend.contexts.optimization.infrastructure.artifacts",
        (
            "resolve_runtime_artifacts",
            "resolve_lambda_selection",
            "validate_runtime_economic_head",
        ),
    ),
    ("backend.contexts.optimization.domain.optimizer", ("optimize",)),
    ("backend.contexts.policy.domain.fixed_point", ("FixedPointResult", "resolve")),
    ("backend.contexts.policy.domain.theta", ("default_theta",)),
    ("backend.contexts.schedule.domain.case_limits", ("YearlyProduction", "apply_case_limits")),
    ("backend.contexts.schedule.domain.canonical", ("canonicalize",)),
    (
        "backend.contexts.schedule.domain.validate",
        ("ViolationKind", "validate_static"),
    ),
    ("backend.contexts.schedule.domain.validate_dynamic", ("validate_dynamic",)),
    (
        "backend.contexts.schedule.domain.validate_dynamic",
        ("FIRST_CONTROL_DECK_DATE_INDEX", "year_of_step"),
    ),
    ("backend.shared.resources", ("chdd_python_dir", "model_z_dir")),
    ("backend.contexts.constraints.application.cases", ("load_case",)),
    ("backend.shared.paths", ("data_root",)),
    ("backend.contexts.constraints.infrastructure.constraints_io", ("constraints_hash",)),
    ("backend.shared.errors", ("ConfigurationError",)),
    ("backend.shared.settings", ("Settings",)),
    ("backend.shared.json_io", ("read_json",)),
    (
        "backend.contexts.optimization.domain.errors",
        (
            "BhpToleranceError",
            "ConnectivitySearchError",
            "OpmBudgetError",
            "SearchRunError",
        ),
    ),
    (
        "backend.contexts.optimization.application.finalist_selection",
        ("evaluate_finalists",),
    ),
)


def _run_search_module(overrides: Mapping[str, object]) -> dict[str, object]:
    module = _module_ast(RUN_SOURCE)
    body = [
        node
        for node in module.body
        if not isinstance(node, (ast.Import, ast.ImportFrom))
        and not (
            isinstance(node, ast.Expr)
            and isinstance(node.value, ast.Call)
            and ast.unparse(node.value).startswith("sys.stdout")
        )
    ]
    holder = types.ModuleType("search_run_under_test")
    namespace = holder.__dict__
    namespace.update(_run_search_import_namespace())
    namespace.update(overrides)
    sys.modules["search_run_under_test"] = holder
    try:
        exec(
            compile(ast.Module(body=body, type_ignores=[]), str(RUN_SOURCE), "exec"),
            namespace,
        )
    finally:
        sys.modules.pop("search_run_under_test", None)
    namespace.update(overrides)
    return namespace


def _run_search_stubs(
    path: str, captured: dict, feature_context: Path = Path("f.json")
) -> dict[str, object]:
    env = SimpleNamespace(
        model=SimpleNamespace(version="model-1"),
        lambda_=SimpleNamespace(window_start="a", window_end="b", stability=1.0),
        scenario_ood=SimpleNamespace(version="ood-1", threshold=0.0),
        npv_head=SimpleNamespace(version="head-1"),
        ood_threshold=0.0,
        constraints=object(),
        base_schedule=object(),
        control_dates=(),
        oil_density_t_per_m3=0.9,
    )
    final = SimpleNamespace(
        npv=1.0,
        iterations=3,
        self_consistent=path == "converged",
        converged=True,
        ood_score=0.0,
        schedule=object(),
    )
    check = SimpleNamespace(ok=True, violations=(), n_control_events=1)
    dynamic = SimpleNamespace(blocking_violations=())
    evaluated = SimpleNamespace(
        npv=1.0,
        npv_parts={},
        sigma=None,
        physics={"complete": 1, "admissible": 1, "blocking_count": 0},
        ood_worst=None,
        ood_score=0.0,
    )
    history = (
        ()
        if path == "fallback"
        else (
            SimpleNamespace(
                theta=SimpleNamespace(values={"a": 1.0}),
                result=SimpleNamespace(objective=1.0),
            ),
        )
    )
    report = SimpleNamespace(
        evaluations=1,
        generations=1,
        stop_reason="done",
        feasible_found=len(history),
        history=(),
        feasible_history=history,
    )
    return {
        "resolve_lambda_selection": lambda **_: SimpleNamespace(
            path=Path(path) / "lambda.json",
            as_provenance=lambda: {},
        ),
        "resolve_runtime_artifacts": lambda: SimpleNamespace(
            scenario_ood=Path("ood.pt"),
            checkpoint=Path("c.json"),
            feature_context=feature_context,
            npv_head=Path("h.pt"),
            npv_calibration=None,
            source="test",
        ),
        "load_case": lambda _: Constraints(),
        "load_environment": lambda **_: env,
        "validate_runtime_economic_head": lambda *_: None,
        "load_response_artifact": lambda _: object(),
        "make_evaluator": lambda _: (lambda schedule: evaluated),
        "make_policy": lambda *args, **kwargs: object(),
        "_search_theta": lambda _: SimpleNamespace(values={"a": 1.0}),
        "optimize": lambda *args, **kwargs: report,
        "resolve": lambda *args, **kwargs: final,
        "validate_static": lambda *args, **kwargs: check,
        "hash_schedule": lambda _: "hash",
        "_repair_predicted_water_balance": lambda *args, **kwargs: (
            object(),
            evaluated,
            dynamic,
            0,
        ),
        "BASE_NPV": 1.0,
        "SURROGATE_NONBLOCKING_KINDS": frozenset(),
        "OutOfDomainScheduleError": ValueError,
        "PhysicallyImpossibleScheduleError": ValueError,
        "OptimizerResult": SimpleNamespace,
        "ScenarioViolation": SimpleNamespace,
        "model_z_dir": lambda: Path("model-z"),
        "chdd_python_dir": lambda: Path("chdd"),
        "evaluate_finalists": lambda ranked, **kwargs: (
            []
            if not ranked
            else [
                (
                    evaluated.npv,
                    ranked[0].theta,
                    object(),
                    final,
                    check,
                    (),
                    "hash",
                    evaluated.sigma,
                )
            ],
            [],
        ),
        "_write_diagnostics_head": lambda **kwargs: None,
        "_write_diagnostics_tail": lambda *args, **kwargs: None,
        "select_finalist": lambda finalists, _beta: finalists[0],
    }


def test_main_path_claims_the_equilibrium_only_when_it_was_reached(
    tmp_path: Path,
) -> None:
    reached = _provenance_from("converged", tmp_path)
    assert reached["search_strategy"] == "cma-es"
    assert reached["policy_equilibrium"] == "reached"

    unreached = _provenance_from("unconverged", tmp_path)
    assert unreached["search_strategy"] == "cma-es"
    assert unreached["policy_equilibrium"] == "not-claimed"


def test_fallback_path_marks_the_equilibrium_as_not_claimed(
    tmp_path: Path,
) -> None:
    provenance = _provenance_from("fallback", tmp_path)

    assert provenance["search_strategy"] == "baseline-neighborhood"
    assert provenance["policy_equilibrium"] == "not-claimed"
    assert provenance["selected_candidate"] == "baseline"


def test_seeded_provenance_already_names_both_fields() -> None:
    source = Path(
        importlib.import_module(
            "backend.contexts.optimization.application.search_provenance"
        ).__file__
    ).read_text(encoding="utf-8")
    seeded = ast.unparse(_function_def(ast.parse(source), "build_search_provenance"))

    assert "'search_strategy': 'cma-es'" in seeded
    assert "'policy_equilibrium': 'not-claimed'" in seeded


def test_default_caps_keep_the_current_behaviour() -> None:
    module = _reload_search_run({})

    assert module.SEARCH_CAP == 2
    assert module.FINAL_CAP == 8
    assert module.DEFAULT_SEARCH_CAP == 2
    assert module.DEFAULT_FINAL_CAP == 8


def test_caps_are_read_from_the_environment() -> None:
    module = _reload_search_run(
        {
            "AIOS_SEARCH_FIXED_POINT_CAP": "6",
            "AIOS_FINAL_FIXED_POINT_CAP": "12",
        }
    )

    assert module.SEARCH_CAP == 6
    assert module.FINAL_CAP == 12


@pytest.mark.parametrize("value", ["0", "-1", "two", ""])
def test_an_unusable_cap_is_an_error_not_a_silent_default(value: str) -> None:
    with pytest.raises(Exception) as error:
        _reload_search_run({"AIOS_SEARCH_FIXED_POINT_CAP": value})

    assert "AIOS_SEARCH_FIXED_POINT_CAP" in str(error.value)


def test_run_search_takes_the_caps_as_arguments() -> None:
    module = _context_module_ast(RUN_SOURCE)
    run_search = _function_def(module, "run_search")
    names = {argument.arg for argument in run_search.args.kwonlyargs}

    assert {"search_cap", "final_cap"} <= names
    source = _run_path_source()
    assert "initial, search_cap)" in source
    assert "initial, final_cap\n" in source or "initial, final_cap)" in source
    assert "'search_fixed_point_cap': str(search_cap)" in source
    assert "'final_fixed_point_cap': str(final_cap)" in source


def test_a_non_positive_cap_argument_is_refused() -> None:
    module = _reload_search_run({})

    with pytest.raises(module.SearchRunError, match="must be positive"):
        module.run_search(search_cap=0)
    with pytest.raises(module.SearchRunError, match="must be positive"):
        module.run_search(final_cap=-3)


@pytest.mark.parametrize(
    "path", [RUN_SOURCE, SEARCH_SOURCE, ARTIFACTS_SOURCE]
)
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
