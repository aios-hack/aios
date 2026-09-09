from __future__ import annotations

import ast
import importlib
import importlib.abc
import importlib.machinery
import io
import json
import sys
import tokenize
import types
from datetime import date
from pathlib import Path
from typing import Any, Iterator

import pytest

from backend.core.contracts import (
    Availability,
    ControlEvent,
    EventKind,
    OperatingStatus,
    Role,
    Schedule,
    ScheduleMeta,
    WellState,
    hash_schedule,
)
from backend.domain.configuration.constraints_io import (
    constraints_from_json,
    constraints_hash,
    constraints_to_json,
)

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
    def create_module(self, spec: importlib.machinery.ModuleSpec) -> types.ModuleType:
        return _StubModule(spec.name)

    def exec_module(self, module: types.ModuleType) -> None:
        pass


class _StubFinder(importlib.abc.MetaPathFinder):
    def find_spec(
        self, name: str, path: Any = None, target: Any = None
    ) -> importlib.machinery.ModuleSpec | None:
        if name in TORCH_PACKAGES:
            return importlib.machinery.ModuleSpec(name, _StubLoader(), is_package=True)
        return None


def _install_torch_stub() -> None:
    if "torch" in sys.modules:
        return
    sys.meta_path.insert(0, _StubFinder())
    for name in TORCH_PACKAGES:
        importlib.import_module(name)
    for name in TORCH_PACKAGES[1:]:
        parent, _, leaf = name.rpartition(".")
        setattr(sys.modules[parent], leaf, sys.modules[name])


def _load_module() -> Any:
    try:
        import torch  # noqa: F401
    except ImportError:
        _install_torch_stub()
    return importlib.import_module(
        "backend.application.optimization.verification_run"
    )


verification_run = _load_module()


def _schedule(setpoint: float = 50.0) -> Schedule:
    return Schedule(
        meta=ScheduleMeta(wells=("I1", "P1"), provenance="test-guard"),
        initial_state={
            "I1": WellState(
                availability=Availability.AVAILABLE,
                role=Role.INJ,
                operating_status=OperatingStatus.OPEN,
                setpoint=200.0,
            ),
            "P1": WellState(
                availability=Availability.AVAILABLE,
                role=Role.PROD,
                operating_status=OperatingStatus.OPEN,
                setpoint=setpoint,
            ),
        },
        fixed_deck_events=(),
        control_events=(
            ControlEvent(
                control_step=0,
                well="P1",
                kind=EventKind.SET_LRAT,
                value=setpoint,
            ),
        ),
    )


CASE_A: dict[str, Any] = {
    "injection_limits": {"2007": 1000.0},
    "liquid_limits": {"2007": 900.0},
    "production_floors": {"2007": 10.0},
    "watercut_limits": {"2007": 0.9},
    "well_outages": [],
    "infrastructure": {},
}

CASE_B: dict[str, Any] = {
    **CASE_A,
    "liquid_limits": {"2007": 800.0},
}


def _constraints(document: dict[str, Any]):
    return constraints_from_json(document)


@pytest.fixture(autouse=True)
def _neutral_module_constant(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    monkeypatch.setattr(verification_run, "EXPECTED_HASH", None, raising=False)
    yield


@pytest.fixture
def runner_spy(monkeypatch: pytest.MonkeyPatch) -> dict[str, int]:
    calls = {"submit": 0, "tract": 0}

    def _submit(*args: Any, **kwargs: Any) -> Any:
        calls["submit"] += 1
        return types.SimpleNamespace(sound=True)

    def _tract(*args: Any, **kwargs: Any) -> Any:
        calls["tract"] += 1
        return _AnyObject()

    monkeypatch.setattr(verification_run, "submit_schedule", _submit)
    monkeypatch.setattr(verification_run, "OpmDeckEmitter", _tract)
    monkeypatch.setattr(verification_run, "load_normatives", _tract)
    monkeypatch.setattr(verification_run, "model_z_dir", _tract)
    monkeypatch.setattr(verification_run, "chdd_python_dir", lambda: Path("."))
    monkeypatch.setattr(verification_run, "deck_hashes", _tract)
    monkeypatch.setattr(verification_run, "summary_spec_hash", _tract)
    monkeypatch.setattr(verification_run, "canonical_part_hash", _tract)
    monkeypatch.setattr(verification_run, "default_config", _tract)
    monkeypatch.setattr(verification_run, "ArtifactHashes", _tract)
    return calls


def _make_run_dir(
    root: Path,
    schedule: Schedule,
    case: dict[str, Any] | None,
    *,
    manifest_constraints_hash: str | None = None,
    write_manifest: bool = True,
) -> Path:
    run_dir = root / "run-1"
    (run_dir / "inputs").mkdir(parents=True, exist_ok=True)
    (run_dir / "opm").mkdir(parents=True, exist_ok=True)
    if case is not None:
        (run_dir / "inputs" / "constraints.json").write_text(
            json.dumps(case, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    if write_manifest:
        document: dict[str, Any] = {
            "run_id": "run-1",
            "status": "searched",
            "schedule_hash": hash_schedule(schedule),
            "constraints_hash": manifest_constraints_hash,
        }
        (run_dir / "manifest.json").write_text(
            json.dumps(document, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    return run_dir


def test_matching_schedule_hash_lets_the_tract_start(
    tmp_path: Path, runner_spy: dict[str, int]
) -> None:
    schedule = _schedule()
    constraints = _constraints(CASE_A)
    run_dir = _make_run_dir(
        tmp_path,
        schedule,
        CASE_A,
        manifest_constraints_hash=constraints_hash(constraints),
    )
    guarded = verification_run.verify_schedule_with_guard(
        schedule,
        run_dir / "opm",
        constraints=constraints,
    )
    guard = guarded.guard
    assert guard.fully_checked
    assert guard.schedule.holds
    assert guard.constraints.holds
    assert guard.schedule.expected == hash_schedule(schedule)
    assert guard.schedule.source.endswith("manifest.json:schedule_hash")
    assert runner_spy["submit"] == 1


def test_divergent_schedule_hash_stops_before_flow(
    tmp_path: Path, runner_spy: dict[str, int]
) -> None:
    schedule = _schedule()
    constraints = _constraints(CASE_A)
    run_dir = _make_run_dir(
        tmp_path,
        _schedule(setpoint=250.0),
        CASE_A,
        manifest_constraints_hash=constraints_hash(constraints),
    )
    with pytest.raises(verification_run.VerificationGuardError) as error:
        verification_run.verify_schedule(
            schedule,
            run_dir / "opm",
            constraints=constraints,
        )
    assert "canonical_schedule_hash" in str(error.value)
    assert runner_spy["submit"] == 0
    assert runner_spy["tract"] == 0


def test_matching_case_hash_is_accepted(
    tmp_path: Path, runner_spy: dict[str, int]
) -> None:
    schedule = _schedule()
    constraints = _constraints(CASE_A)
    run_dir = _make_run_dir(
        tmp_path,
        schedule,
        CASE_A,
        manifest_constraints_hash=constraints_hash(constraints),
    )
    guarded = verification_run.verify_schedule_with_guard(
        schedule,
        run_dir / "opm",
        constraints=constraints,
    )
    assert guarded.guard.fully_checked
    assert guarded.guard.constraints.holds
    assert runner_spy["submit"] == 1


def test_divergent_case_hash_is_refused(
    tmp_path: Path, runner_spy: dict[str, int]
) -> None:
    schedule = _schedule()
    searched = _constraints(CASE_A)
    swapped = _constraints(CASE_B)
    assert constraints_hash(searched) != constraints_hash(swapped)
    run_dir = _make_run_dir(
        tmp_path,
        schedule,
        CASE_A,
        manifest_constraints_hash=constraints_hash(searched),
    )
    with pytest.raises(verification_run.VerificationGuardError) as error:
        verification_run.verify_schedule(
            schedule,
            run_dir / "opm",
            constraints=swapped,
        )
    assert "constraints_hash" in str(error.value)
    assert runner_spy["submit"] == 0


def test_case_hash_is_recovered_from_saved_inputs_when_manifest_is_silent(
    tmp_path: Path, runner_spy: dict[str, int]
) -> None:
    schedule = _schedule()
    run_dir = _make_run_dir(tmp_path, schedule, CASE_A, manifest_constraints_hash=None)
    with pytest.raises(verification_run.VerificationGuardError):
        verification_run.verify_schedule(
            schedule,
            run_dir / "opm",
            constraints=_constraints(CASE_B),
        )
    assert runner_spy["submit"] == 0


def test_missing_reference_is_reported_instead_of_silently_skipped(
    tmp_path: Path, runner_spy: dict[str, int], capsys: pytest.CaptureFixture[str]
) -> None:
    schedule = _schedule()
    constraints = _constraints(CASE_A)
    work_root = tmp_path / "loose" / "opm"
    guarded = verification_run.verify_schedule_with_guard(
        schedule,
        work_root,
        constraints=constraints,
    )
    guard = guarded.guard
    assert not guard.fully_checked
    assert {check.name for check in guard.unchecked} == {
        "canonical_schedule_hash",
        "constraints_hash",
    }
    for check in guard.checks:
        assert check.expected is None
        assert not check.holds
        assert check.source == "эталон не найден"
    recorded = json.loads(
        (work_root / "verification-guard.json").read_text(encoding="utf-8")
    )
    assert recorded["fully_checked"] is False
    assert sorted(recorded["unchecked"]) == [
        "canonical_schedule_hash",
        "constraints_hash",
    ]
    assert "не сверяется" in capsys.readouterr().out
    assert runner_spy["submit"] == 1


def test_guard_report_is_written_even_when_the_run_is_refused(
    tmp_path: Path, runner_spy: dict[str, int]
) -> None:
    schedule = _schedule()
    constraints = _constraints(CASE_A)
    run_dir = _make_run_dir(
        tmp_path,
        _schedule(setpoint=250.0),
        CASE_A,
        manifest_constraints_hash=constraints_hash(constraints),
    )
    with pytest.raises(verification_run.VerificationGuardError):
        verification_run.verify_schedule(
            schedule,
            run_dir / "opm",
            constraints=constraints,
        )
    recorded = json.loads(
        (run_dir / "opm" / "verification-guard.json").read_text(encoding="utf-8")
    )
    names = {check["name"]: check for check in recorded["checks"]}
    assert names["canonical_schedule_hash"]["holds"] is False
    assert names["constraints_hash"]["holds"] is True


def test_explicit_arguments_win_over_the_run_directory(
    tmp_path: Path, runner_spy: dict[str, int]
) -> None:
    schedule = _schedule()
    constraints = _constraints(CASE_A)
    run_dir = _make_run_dir(
        tmp_path,
        _schedule(setpoint=250.0),
        CASE_B,
        manifest_constraints_hash=constraints_hash(_constraints(CASE_B)),
    )
    guarded = verification_run.verify_schedule_with_guard(
        schedule,
        run_dir / "opm",
        expected_schedule_hash=hash_schedule(schedule),
        expected_constraints_hash=constraints_hash(constraints),
        constraints=constraints,
    )
    assert guarded.guard.fully_checked
    assert runner_spy["submit"] == 1


def test_blank_manifest_hash_is_an_error_not_a_skipped_check(
    tmp_path: Path, runner_spy: dict[str, int]
) -> None:
    schedule = _schedule()
    run_dir = tmp_path / "run-1"
    (run_dir / "inputs").mkdir(parents=True)
    (run_dir / "manifest.json").write_text(
        json.dumps(
            {
                "run_id": "run-1",
                "status": "searched",
                "schedule_hash": "   ",
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    with pytest.raises(verification_run.VerificationGuardError):
        verification_run.verify_schedule(
            schedule,
            run_dir / "opm",
            constraints=_constraints(CASE_A),
        )
    assert runner_spy["submit"] == 0


def test_module_carries_no_comments() -> None:
    source = (
        Path(verification_run.__file__).read_text(encoding="utf-8")
    )
    allowed = ("# type: ignore", "# noqa", "# pragma: no cover")
    for token in tokenize.generate_tokens(io.StringIO(source).readline):
        if token.type == tokenize.COMMENT:
            assert token.string.startswith(allowed), token.string
    tree = ast.parse(source)
    assert ast.get_docstring(tree) is None
    for node in ast.walk(tree):
        if isinstance(
            node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)
        ):
            assert ast.get_docstring(node) is None, node.name


def test_constraints_round_trip_keeps_the_hash_stable() -> None:
    constraints = _constraints(CASE_A)
    again = constraints_from_json(constraints_to_json(constraints))
    assert constraints_hash(again) == constraints_hash(constraints)
