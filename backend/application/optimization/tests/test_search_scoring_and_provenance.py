from __future__ import annotations

import ast
import importlib
import importlib.abc
import importlib.machinery
import io
import json
import os
import sys
import tokenize
import types
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Iterator

import pytest

from backend.application.optimization.runtime_artifacts import (
    RuntimeArtifactError,
    RuntimeArtifacts,
    resolve_runtime_artifacts,
    validate_npv_scoring_is_unambiguous,
)

RUN_SOURCE = Path(__file__).resolve().parents[1] / "search_run.py"
SEARCH_SOURCE = Path(__file__).resolve().parents[1] / "schedule_search.py"
ARTIFACTS_SOURCE = Path(__file__).resolve().parents[1] / "runtime_artifacts.py"

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
        if module.startswith("backend.ml")
        or module.startswith("backend.application.optimization.schedule_search")
        or module.startswith("backend.application.optimization.search_run")
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


def _function_def(module: ast.Module, name: str) -> ast.FunctionDef:
    for node in module.body:
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return node
    raise AssertionError(f"функция {name} не найдена")


def _reload_search_run(environ: dict[str, str]) -> Any:
    saved = {name: os.environ.get(name) for name in environ}
    os.environ.update(environ)
    try:
        sys.modules.pop("backend.application.optimization.search_run", None)
        return _load_module("backend.application.optimization.search_run")
    finally:
        for name, value in saved.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value
        sys.modules.pop("backend.application.optimization.search_run", None)


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
    assert "калибровка" in message
    assert "голова прямого прогноза" in message


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


def _scoring_namespace() -> dict[str, object]:
    module = _module_ast(SEARCH_SOURCE)
    body = [
        node
        for node in module.body
        if (
            isinstance(node, ast.FunctionDef)
            and node.name
            in ("_validate_npv_scoring_is_unambiguous", "predict_economics")
        )
        or (isinstance(node, ast.ClassDef) and node.name == "ScheduleSearchError")
        or (
            isinstance(node, ast.Assign)
            and isinstance(node.targets[0], ast.Name)
            and node.targets[0].id == "_AMBIGUOUS_NPV_SCORING"
        )
    ]
    found = {
        node.name if not isinstance(node, ast.Assign) else node.targets[0].id
        for node in body
    }
    assert found == {
        "ScheduleSearchError",
        "_AMBIGUOUS_NPV_SCORING",
        "_validate_npv_scoring_is_unambiguous",
        "predict_economics",
    }, sorted(found)
    namespace: dict[str, object] = {
        "SearchEnvironment": object,
        "ResponseArtifact": object,
        "analyze_base_case": lambda *args, **kwargs: SimpleNamespace(
            npv_methodology=100.0
        ),
    }
    exec(
        compile(ast.Module(body=body, type_ignores=[]), str(SEARCH_SOURCE), "exec"),
        namespace,
    )
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


def test_calibration_beside_a_head_is_never_silently_dropped_while_scoring() -> None:
    namespace = _scoring_namespace()
    env = _ScoringEnv(_Head(), _Calibration())

    with pytest.raises(namespace["ScheduleSearchError"]) as error:
        namespace["predict_economics"](env, object(), object())

    assert "калибровка" in str(error.value)


def test_calibration_without_a_head_still_shapes_the_number() -> None:
    namespace = _scoring_namespace()
    env = _ScoringEnv(None, _Calibration())

    parts = namespace["predict_economics"](env, object(), object())

    assert parts["physical"] == 100.0
    assert parts["blended"] == 205.0


def test_a_head_without_a_calibration_blends_as_before() -> None:
    namespace = _scoring_namespace()
    env = _ScoringEnv(_Head(), None)

    parts = namespace["predict_economics"](env, object(), object())

    assert parts["direct"] == 200.0
    assert parts["blended"] == pytest.approx(0.75 * 200.0 + 0.25 * 100.0)


def test_load_environment_refuses_the_pair_before_any_candidate_is_scored() -> None:
    source = ast.unparse(_function_def(_module_ast(SEARCH_SOURCE), "load_environment"))

    assert "npv_calibration_path" in source
    assert "_validate_npv_scoring_is_unambiguous(npv_head, npv_calibration)" in source
    assert "npv_calibration=npv_calibration" in source


def test_run_search_hands_the_calibration_to_the_environment() -> None:
    source = ast.unparse(_function_def(_module_ast(RUN_SOURCE), "run_search"))

    assert "npv_calibration_path=artifacts.npv_calibration" in source


def test_both_return_paths_carry_the_strategy_and_the_equilibrium() -> None:
    module = _module_ast(RUN_SOURCE)
    run_search = ast.unparse(_function_def(module, "run_search"))
    fallback = ast.unparse(_function_def(module, "_search_near_baseline"))

    assert "'search_strategy': 'cma-es'" in run_search
    assert "search_strategy='cma-es'" in run_search
    assert "policy_equilibrium" in run_search
    assert "search_strategy='baseline-neighborhood'" in fallback
    assert "policy_equilibrium='not-claimed'" in fallback


def _provenance_from(path: str) -> dict[str, str]:
    module = _module_ast(RUN_SOURCE)
    run_search = _function_def(module, "run_search")
    fallback = _function_def(module, "_search_near_baseline")
    namespace: dict[str, object] = {
        "os": os,
        "Path": Path,
        "SEARCH_CAP": 2,
        "FINAL_CAP": 8,
        "BUDGET": 120,
        "SEED": 20260816,
        "CONSTRAINTS": Path("config/competition-constraints.json"),
        "RESPONSE": Path("data/base_case/response.json"),
        "LAMBDA": Path("data/lambda/lambda.json"),
        "OOD_THRESHOLD": 0.0,
        "SearchRunError": RuntimeError,
        "SearchOutcome": _outcome_factory,
        "print": lambda *args, **kwargs: None,
    }
    captured: dict[str, dict[str, str]] = {}

    def _fallback(env: object, evaluator: object, budget: int, provenance: dict) -> object:
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

    namespace["_search_near_baseline"] = _fallback
    namespace.update(_run_search_stubs(path, captured))
    exec(
        compile(
            ast.Module(body=[run_search], type_ignores=[]), str(RUN_SOURCE), "exec"
        ),
        namespace,
    )
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


def _run_search_stubs(path: str, captured: dict) -> dict[str, object]:
    env = SimpleNamespace(
        model=SimpleNamespace(version="model-1"),
        lambda_=SimpleNamespace(window_start="a", window_end="b", stability=1.0),
        scenario_ood=SimpleNamespace(version="ood-1"),
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
    evaluated = SimpleNamespace(npv=1.0)
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
        "resolve_runtime_artifacts": lambda: SimpleNamespace(
            scenario_ood=Path("ood.pt"),
            checkpoint=Path("c.json"),
            feature_context=Path("f.json"),
            npv_head=Path("h.pt"),
            npv_calibration=None,
            source="test",
        ),
        "load_case": lambda _: object(),
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
        "SEARCH_DIAGNOSTICS": SimpleNamespace(
            parent=SimpleNamespace(mkdir=lambda **_: None),
            write_text=lambda *args, **kwargs: None,
        ),
        "json": json,
        "math": __import__("math"),
        "time": __import__("time"),
        "FINALIST_CAP": 4,
        "BASE_NPV": 1.0,
        "SURROGATE_NONBLOCKING_KINDS": frozenset(),
        "OutOfDomainScheduleError": ValueError,
        "PhysicallyImpossibleScheduleError": ValueError,
        "OptimizerResult": SimpleNamespace,
        "ScenarioViolation": SimpleNamespace,
        "model_z_dir": lambda: Path("model-z"),
        "chdd_python_dir": lambda: Path("chdd"),
    }


def test_main_path_claims_the_equilibrium_only_when_it_was_reached() -> None:
    reached = _provenance_from("converged")
    assert reached["search_strategy"] == "cma-es"
    assert reached["policy_equilibrium"] == "reached"

    unreached = _provenance_from("unconverged")
    assert unreached["search_strategy"] == "cma-es"
    assert unreached["policy_equilibrium"] == "not-claimed"


def test_fallback_path_marks_the_equilibrium_as_not_claimed() -> None:
    provenance = _provenance_from("fallback")

    assert provenance["search_strategy"] == "baseline-neighborhood"
    assert provenance["policy_equilibrium"] == "not-claimed"
    assert provenance["selected_candidate"] == "baseline"


def test_seeded_provenance_already_names_both_fields() -> None:
    source = ast.unparse(_function_def(_module_ast(RUN_SOURCE), "run_search"))
    seeded = source.split("calls = ")[0]

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


@pytest.mark.parametrize("value", ["0", "-1", "два", ""])
def test_an_unusable_cap_is_an_error_not_a_silent_default(value: str) -> None:
    with pytest.raises(Exception) as error:
        _reload_search_run({"AIOS_SEARCH_FIXED_POINT_CAP": value})

    assert "AIOS_SEARCH_FIXED_POINT_CAP" in str(error.value)


def test_run_search_takes_the_caps_as_arguments() -> None:
    module = _module_ast(RUN_SOURCE)
    run_search = _function_def(module, "run_search")
    names = {argument.arg for argument in run_search.args.kwonlyargs}

    assert {"search_cap", "final_cap"} <= names
    source = ast.unparse(run_search)
    assert "initial, search_cap)" in source
    assert "initial, final_cap\n" in source or "initial, final_cap)" in source
    assert "'search_fixed_point_cap': str(search_cap)" in source
    assert "'final_fixed_point_cap': str(final_cap)" in source


def test_a_non_positive_cap_argument_is_refused() -> None:
    module = _reload_search_run({})

    with pytest.raises(module.SearchRunError, match="положительным"):
        module.run_search(search_cap=0)
    with pytest.raises(module.SearchRunError, match="положительным"):
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
