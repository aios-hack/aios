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

from backend.contexts.schedule.domain.schedule import (
    Availability,
    ControlEvent,
    EventKind,
    OperatingStatus,
    Role,
    Schedule,
    ScheduleMeta,
    WellState,
)
from backend.contexts.constraints.domain.constraints import Constraints
from backend.shared.hashing import hash_schedule
from backend.contexts.constraints.infrastructure.constraints_io import constraints_hash
from backend.contexts.schedule.domain.case_limits import CaseLimitsOutcome, YearlyProduction

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


def _load_module() -> Any:
    stubbed: list[str] = []
    try:
        import torch  # noqa: F401
    except ImportError:
        stubbed = _install_torch_stub()
    try:
        return importlib.import_module(
            "backend.contexts.optimization.application.verification_run"
        )
    finally:
        if stubbed:
            for name in [
                module
                for module in sys.modules
                if module.startswith("backend.contexts.surrogate")
                or module.startswith("backend.contexts.optimization.application.environment")
            ]:
                sys.modules.pop(name, None)
            for name in reversed(stubbed):
                sys.modules.pop(name, None)


verification_run = _load_module()

DATES: tuple[date, ...] = (date(2007, 1, 1), date(2007, 4, 1), date(2007, 7, 1))


def _schedule(setpoint: float, provenance: str = "test-comparison") -> Schedule:
    return Schedule(
        meta=ScheduleMeta(wells=("I1", "P1"), provenance=provenance),
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
                control_step=0, well="P1", kind=EventKind.SET_LRAT, value=setpoint
            ),
        ),
    )


BASELINE = _schedule(120.0, "baseline")
CANDIDATE = _schedule(90.0, "candidate")
CASE = Constraints(liquid_limits={2007: 100.0})


def _forecast(scale: float) -> Any:
    def forecast(schedule: Schedule) -> YearlyProduction:
        total = sum(float(event.value or 0.0) for event in schedule.control_events)
        return YearlyProduction(liquid_by_year={2007: total * scale})

    return forecast


class _StubViolation:
    def __init__(self, kind: str) -> None:
        self.kind = kind


class _StubDynamicReport:
    def __init__(self, violations: int, blocking: int) -> None:
        self.violations = tuple(_StubViolation("MASS_BALANCE") for _ in range(violations))
        self.blocking_violations = tuple(
            _StubViolation("MASS_BALANCE") for _ in range(blocking)
        )


class _StubStaticReport:
    def __init__(self, violations: int = 0) -> None:
        self.violations = tuple(_StubViolation("STATIC") for _ in range(violations))


class _StubOpmRun:
    def __init__(self, run_id: str, status: str) -> None:
        self.run_id = run_id
        self.status = status


class _StubFinalNpv:
    def __init__(self, npv: float) -> None:
        self.npv_methodology = npv


class _StubResult:
    def __init__(
        self,
        *,
        npv: float | None,
        run_id: str,
        violations: int = 0,
        blocking: int = 0,
        status: str = "RunStatus.OK",
        with_dynamic: bool = True,
    ) -> None:
        self.final_npv = None if npv is None else _StubFinalNpv(npv)
        self.opm_run = _StubOpmRun(run_id, status)
        self.static_report = _StubStaticReport()
        self.dynamic_report = (
            _StubDynamicReport(violations, blocking) if with_dynamic else None
        )
        self.identities = ()
        self.failed_identities = ()
        self.sound = npv is not None and blocking == 0


def _guard(constraints_actual: str) -> Any:
    check = verification_run.GuardCheck(
        name="constraints_hash",
        expected=constraints_actual,
        actual=constraints_actual,
        source="test",
    )
    schedule_check = verification_run.GuardCheck(
        name="canonical_schedule_hash",
        expected="s",
        actual="s",
        source="test",
    )
    return verification_run.GuardReport(schedule=schedule_check, constraints=check)


def _side(
    name: str,
    schedule: Schedule,
    *,
    npv: float | None,
    constraints_actual: str,
    violations: int = 0,
    blocking: int = 0,
    wallclock: float = 1.0,
    with_dynamic: bool = True,
    projection: CaseLimitsOutcome | None = None,
) -> Any:
    return verification_run.ComparisonSide(
        name=name,
        schedule=schedule,
        result=_StubResult(
            npv=npv,
            run_id=f"run-{name}",
            violations=violations,
            blocking=blocking,
            with_dynamic=with_dynamic,
        ),
        guard=_guard(constraints_actual),
        wallclock_seconds=wallclock,
        opm_runs=1,
        projection=projection,
    )


@pytest.fixture
def stub_tract(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    calls: dict[str, Any] = {"verify": 0, "schedules": [], "roots": [], "decks": 0}

    def _deck(schedule: Schedule, model_dir: Path) -> str:
        calls["decks"] += 1
        return "deck-template-hash"

    monkeypatch.setattr(verification_run, "_deck_template_hash", _deck)
    return calls


def _verifier(
    calls: dict[str, Any], npv_by_name: dict[str, float | None]
) -> Any:
    def verifier(schedule: Schedule, work_root: Path) -> Any:
        calls["verify"] += 1
        calls["schedules"].append(hash_schedule(schedule))
        calls["roots"].append(work_root.name)
        name = "baseline" if work_root.name.endswith("baseline") else "candidate"
        return verification_run.GuardedVerification(
            result=_StubResult(npv=npv_by_name[name], run_id=f"run-{name}"),
            guard=_guard(constraints_hash(CASE)),
        )

    return verifier


def test_delta_is_computed_on_known_numbers() -> None:
    actual = constraints_hash(CASE)
    document = verification_run.build_comparison_document(
        _side("baseline", BASELINE, npv=7_781_000_000.0, constraints_actual=actual),
        _side("candidate", CANDIDATE, npv=11_873_000_000.0, constraints_actual=actual),
        case_path=Path("config/cases/base.json"),
        case_hash=actual,
        baseline_deck_hash="deck",
        candidate_deck_hash="deck",
        image="opm:test",
        run_id="run-1",
    )
    delta = document["delta"]
    assert delta["npv_rub"] == pytest.approx(4_092_000_000.0)
    assert delta["npv_bln_rub"] == pytest.approx(4.092)
    assert delta["npv_percent"] == pytest.approx(
        100.0 * 4_092_000_000.0 / 7_781_000_000.0
    )


def test_document_carries_both_npvs_violations_wallclock_and_run_count() -> None:
    actual = constraints_hash(CASE)
    document = verification_run.build_comparison_document(
        _side(
            "baseline",
            BASELINE,
            npv=7.0e9,
            constraints_actual=actual,
            violations=5,
            blocking=2,
            wallclock=61.5,
        ),
        _side(
            "candidate",
            CANDIDATE,
            npv=8.0e9,
            constraints_actual=actual,
            violations=1,
            blocking=0,
            wallclock=64.5,
        ),
        case_path=Path("config/cases/base.json"),
        case_hash=actual,
        baseline_deck_hash="deck",
        candidate_deck_hash="deck",
        image="opm:test",
        run_id="run-1",
    )
    assert document["baseline"]["npv_rub"] == 7.0e9
    assert document["candidate"]["npv_rub"] == 8.0e9
    assert document["delta"]["npv_rub"] == pytest.approx(1.0e9)
    assert document["baseline"]["violations"]["dynamic"] == 5
    assert document["baseline"]["violations"]["blocking"] == 2
    assert document["candidate"]["violations"]["blocking"] == 0
    assert document["delta"]["blocking_violations"] == -2
    assert document["baseline"]["wallclock_seconds"] == 61.5
    assert document["candidate"]["wallclock_seconds"] == 64.5
    assert document["totals"]["wallclock_seconds"] == pytest.approx(126.0)
    assert document["totals"]["opm_runs"] == 2
    assert document["baseline"]["opm_runs"] == 1
    metrics = {row["metric"] for row in document["table"]}
    assert "NPV, bln RUB" in metrics
    assert "OPM runs" in metrics


def test_divergent_case_hash_between_sides_refuses_the_comparison() -> None:
    other = Constraints(liquid_limits={2007: 55.0})
    with pytest.raises(verification_run.ComparisonError) as error:
        verification_run.build_comparison_document(
            _side(
                "baseline", BASELINE, npv=7.0e9, constraints_actual=constraints_hash(CASE)
            ),
            _side(
                "candidate",
                CANDIDATE,
                npv=8.0e9,
                constraints_actual=constraints_hash(other),
            ),
            case_path=Path("config/cases/base.json"),
            case_hash=constraints_hash(CASE),
            baseline_deck_hash="deck",
            candidate_deck_hash="deck",
            image="opm:test",
            run_id="run-1",
        )
    assert "constraints_hash" in str(error.value)
    assert "not made under the same conditions" in str(error.value)


def test_divergent_deck_hash_between_sides_refuses_the_comparison() -> None:
    actual = constraints_hash(CASE)
    with pytest.raises(verification_run.ComparisonError) as error:
        verification_run.build_comparison_document(
            _side("baseline", BASELINE, npv=7.0e9, constraints_actual=actual),
            _side("candidate", CANDIDATE, npv=8.0e9, constraints_actual=actual),
            case_path=Path("config/cases/base.json"),
            case_hash=actual,
            baseline_deck_hash="deck-a",
            candidate_deck_hash="deck-b",
            image="opm:test",
            run_id="run-1",
        )
    assert "deck_hash" in str(error.value)


def test_missing_npv_on_a_side_is_refused_not_replaced_by_zero() -> None:
    actual = constraints_hash(CASE)
    with pytest.raises(verification_run.ComparisonError) as error:
        verification_run.build_comparison_document(
            _side("baseline", BASELINE, npv=7.0e9, constraints_actual=actual),
            _side(
                "candidate",
                CANDIDATE,
                npv=None,
                constraints_actual=actual,
                with_dynamic=False,
            ),
            case_path=Path("config/cases/base.json"),
            case_hash=actual,
            baseline_deck_hash="deck",
            candidate_deck_hash="deck",
            image="opm:test",
            run_id="run-1",
        )
    message = str(error.value)
    assert "candidate" in message
    assert "produced no NPV" in message
    assert "zero" in message


def test_missing_baseline_npv_is_refused_too() -> None:
    actual = constraints_hash(CASE)
    with pytest.raises(verification_run.ComparisonError) as error:
        verification_run.build_comparison_document(
            _side(
                "baseline",
                BASELINE,
                npv=None,
                constraints_actual=actual,
                with_dynamic=False,
            ),
            _side("candidate", CANDIDATE, npv=8.0e9, constraints_actual=actual),
            case_path=Path("config/cases/base.json"),
            case_hash=actual,
            baseline_deck_hash="deck",
            candidate_deck_hash="deck",
            image="opm:test",
            run_id="run-1",
        )
    assert "baseline" in str(error.value)


def test_projection_without_a_forecast_is_an_explicit_refusal() -> None:
    with pytest.raises(verification_run.ComparisonError) as error:
        verification_run.project_baseline(BASELINE, CASE, DATES, None)
    message = str(error.value)
    assert "production forecast" in message
    assert "sum of setpoints" in message


def test_projection_with_a_forecast_uses_it_and_reports_the_trim() -> None:
    outcome = verification_run.project_baseline(BASELINE, CASE, DATES, _forecast(1.0))
    assert outcome.forecast_used is True
    assert outcome.setpoint_sum_fallback is False
    assert outcome.trimmed_years[EventKind.SET_LRAT] == (2007,)


def test_projection_failure_is_reported_with_its_reason() -> None:
    def blind(schedule: Schedule) -> YearlyProduction:
        return YearlyProduction(liquid_by_year={})

    with pytest.raises(verification_run.ComparisonError) as error:
        verification_run.project_baseline(BASELINE, CASE, DATES, blind)
    assert "was not projected onto the case" in str(error.value)


def test_comparison_writes_the_json_under_the_run_directory(
    tmp_path: Path, stub_tract: dict[str, Any]
) -> None:
    document = verification_run.compare_baseline_to_candidate(
        run_id="run-1",
        case_path=Path("config/cases/base.json"),
        constraints=CASE,
        baseline_schedule=BASELINE,
        candidate_schedule=CANDIDATE,
        control_dates=DATES,
        forecast=_forecast(1.0),
        runs_root=tmp_path,
        model_dir=tmp_path / "model",
        verifier=_verifier(
            stub_tract, {"baseline": 7.781e9, "candidate": 11.873e9}
        ),
    )
    path = tmp_path / "run-1" / "comparison.json"
    assert path.is_file()
    saved = json.loads(path.read_text(encoding="utf-8"))
    assert saved == document
    assert saved["schema_version"] == verification_run.COMPARISON_SCHEMA_VERSION
    assert saved["conditions"]["equal"] is True
    assert saved["conditions"]["case_hash"] == constraints_hash(CASE)
    assert saved["conditions"]["deck_hash"] == "deck-template-hash"
    assert saved["conditions"]["opm_image"]
    assert saved["baseline"]["case_projection"]["forecast_used"] is True
    assert saved["candidate"]["case_projection"] is None
    assert saved["delta"]["npv_rub"] == pytest.approx(11.873e9 - 7.781e9)
    assert stub_tract["verify"] == 2
    assert stub_tract["roots"] == ["opm-baseline", "opm-candidate"]


def test_comparison_runs_the_projected_baseline_not_the_raw_one(
    tmp_path: Path, stub_tract: dict[str, Any]
) -> None:
    verification_run.compare_baseline_to_candidate(
        run_id="run-1",
        case_path=Path("config/cases/base.json"),
        constraints=CASE,
        baseline_schedule=BASELINE,
        candidate_schedule=CANDIDATE,
        control_dates=DATES,
        forecast=_forecast(1.0),
        runs_root=tmp_path,
        model_dir=tmp_path / "model",
        verifier=_verifier(stub_tract, {"baseline": 7.0e9, "candidate": 8.0e9}),
    )
    assert stub_tract["schedules"][0] != hash_schedule(BASELINE)
    assert stub_tract["schedules"][1] == hash_schedule(CANDIDATE)


def test_comparison_without_a_forecast_never_reaches_opm(
    tmp_path: Path, stub_tract: dict[str, Any]
) -> None:
    with pytest.raises(verification_run.ComparisonError):
        verification_run.compare_baseline_to_candidate(
            run_id="run-1",
            case_path=Path("config/cases/base.json"),
            constraints=CASE,
            baseline_schedule=BASELINE,
            candidate_schedule=CANDIDATE,
            control_dates=DATES,
            forecast=None,
            runs_root=tmp_path,
            model_dir=tmp_path / "model",
            verifier=_verifier(stub_tract, {"baseline": 7.0e9, "candidate": 8.0e9}),
        )
    assert stub_tract["verify"] == 0
    assert not (tmp_path / "run-1" / "comparison.json").exists()


def test_comparison_refuses_when_a_side_yields_no_npv(
    tmp_path: Path, stub_tract: dict[str, Any]
) -> None:
    with pytest.raises(verification_run.ComparisonError):
        verification_run.compare_baseline_to_candidate(
            run_id="run-1",
            case_path=Path("config/cases/base.json"),
            constraints=CASE,
            baseline_schedule=BASELINE,
            candidate_schedule=CANDIDATE,
            control_dates=DATES,
            forecast=_forecast(1.0),
            runs_root=tmp_path,
            model_dir=tmp_path / "model",
            verifier=_verifier(stub_tract, {"baseline": 7.0e9, "candidate": None}),
        )
    assert not (tmp_path / "run-1" / "comparison.json").exists()


def test_comparison_table_is_ready_for_the_screen_without_arithmetic(
    tmp_path: Path, stub_tract: dict[str, Any]
) -> None:
    document = verification_run.compare_baseline_to_candidate(
        run_id="run-1",
        case_path=Path("config/cases/base.json"),
        constraints=CASE,
        baseline_schedule=BASELINE,
        candidate_schedule=CANDIDATE,
        control_dates=DATES,
        forecast=_forecast(1.0),
        runs_root=tmp_path,
        model_dir=tmp_path / "model",
        verifier=_verifier(stub_tract, {"baseline": 7.0e9, "candidate": 8.0e9}),
    )
    rows = {row["metric"]: row for row in document["table"]}
    assert rows["NPV, bln RUB"]["baseline"] == "7.000"
    assert rows["NPV, bln RUB"]["candidate"] == "8.000"
    assert rows["NPV, bln RUB"]["delta"] == "+1.000"
    assert rows["OPM runs"]["delta"] == "2"
    for row in document["table"]:
        assert set(row) == {"metric", "baseline", "candidate", "delta"}
        assert all(isinstance(value, str) for value in row.values())


def test_print_comparison_renders_every_row(
    tmp_path: Path, stub_tract: dict[str, Any], capsys: pytest.CaptureFixture[str]
) -> None:
    document = verification_run.compare_baseline_to_candidate(
        run_id="run-1",
        case_path=Path("config/cases/base.json"),
        constraints=CASE,
        baseline_schedule=BASELINE,
        candidate_schedule=CANDIDATE,
        control_dates=DATES,
        forecast=_forecast(1.0),
        runs_root=tmp_path,
        model_dir=tmp_path / "model",
        verifier=_verifier(stub_tract, {"baseline": 7.0e9, "candidate": 8.0e9}),
    )
    verification_run.print_comparison(document)
    out = capsys.readouterr().out
    for row in document["table"]:
        assert row["metric"] in out


def test_comparison_module_carries_no_comments() -> None:
    source = Path(verification_run.__file__).read_text(encoding="utf-8")
    allowed = ("# type: ignore", "# noqa", "# pragma: no cover")
    for token in tokenize.generate_tokens(io.StringIO(source).readline):
        if token.type == tokenize.COMMENT:
            assert token.string.startswith(allowed), token.string
    tree = ast.parse(source)
    assert ast.get_docstring(tree) is None
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            assert ast.get_docstring(node) is None, node.name


def test_comparison_document_carries_every_required_field(
    tmp_path: Path, stub_tract: dict[str, Any]
) -> None:
    document = verification_run.compare_baseline_to_candidate(
        run_id="run-1",
        case_path=Path("config/cases/base.json"),
        constraints=CASE,
        baseline_schedule=BASELINE,
        candidate_schedule=CANDIDATE,
        control_dates=DATES,
        forecast=_forecast(1.0),
        runs_root=tmp_path,
        model_dir=tmp_path / "model",
        verifier=_verifier(stub_tract, {"baseline": 7.781e9, "candidate": 11.873e9}),
    )
    saved = json.loads(
        (tmp_path / "run-1" / "comparison.json").read_text(encoding="utf-8")
    )
    assert set(saved) == {
        "schema_version",
        "run_id",
        "conditions",
        "baseline",
        "candidate",
        "delta",
        "totals",
        "table",
    }
    for name in ("baseline", "candidate"):
        side = saved[name]
        assert set(side) == {
            "name",
            "canonical_schedule_hash",
            "npv_rub",
            "npv_bln_rub",
            "run_id",
            "run_status",
            "sound",
            "violations",
            "failed_identities",
            "wallclock_seconds",
            "opm_runs",
            "case_projection",
        }
        assert set(side["violations"]) == {
            "static",
            "dynamic",
            "blocking",
            "by_kind",
        }
        assert isinstance(side["npv_rub"], float)
        assert isinstance(side["wallclock_seconds"], float)
        assert side["opm_runs"] == 1
    assert set(saved["delta"]) == {
        "npv_rub",
        "npv_bln_rub",
        "npv_percent",
        "blocking_violations",
        "wallclock_seconds",
    }
    assert set(saved["totals"]) == {"opm_runs", "wallclock_seconds"}
    assert saved["totals"]["opm_runs"] == 2


def test_comparison_conditions_name_the_case_and_the_opm_image(
    tmp_path: Path, stub_tract: dict[str, Any]
) -> None:
    document = verification_run.compare_baseline_to_candidate(
        run_id="run-1",
        case_path=Path("config/cases/base.json"),
        constraints=CASE,
        baseline_schedule=BASELINE,
        candidate_schedule=CANDIDATE,
        control_dates=DATES,
        forecast=_forecast(1.0),
        runs_root=tmp_path,
        model_dir=tmp_path / "model",
        verifier=_verifier(stub_tract, {"baseline": 7.0e9, "candidate": 8.0e9}),
    )
    conditions = document["conditions"]
    assert set(conditions) == {
        "equal",
        "case_path",
        "case_hash",
        "constraints_hash",
        "deck_hash",
        "opm_image",
        "git_commit",
        "checks",
    }
    assert conditions["equal"] is True
    assert conditions["case_path"] == str(Path("config/cases/base.json"))
    assert conditions["case_hash"] == constraints_hash(CASE)
    assert conditions["constraints_hash"] == constraints_hash(CASE)
    checks = {check["name"]: check for check in conditions["checks"]}
    assert set(checks) == {
        "constraints_hash",
        "case_hash",
        "deck_hash",
        "opm_image",
    }
    for check in checks.values():
        assert check["holds"] is True
        assert check["baseline"] == check["candidate"]


def test_divergent_opm_image_between_sides_refuses_the_comparison() -> None:
    actual = constraints_hash(CASE)
    checks = (
        verification_run.ConditionCheck(
            name="opm_image", baseline="opm:a", candidate="opm:b"
        ),
    )
    with pytest.raises(verification_run.ComparisonError) as error:
        verification_run.refuse_unequal_conditions(checks)
    message = str(error.value)
    assert "opm_image" in message
    assert "not made under the same conditions" in message
    assert actual not in message


def test_equal_conditions_flags_the_side_that_diverges() -> None:
    other = Constraints(liquid_limits={2007: 55.0})
    checks = verification_run.equal_conditions(
        _side(
            "baseline", BASELINE, npv=7.0e9, constraints_actual=constraints_hash(CASE)
        ),
        _side(
            "candidate",
            CANDIDATE,
            npv=8.0e9,
            constraints_actual=constraints_hash(other),
        ),
        case_hash=constraints_hash(CASE),
        baseline_deck_hash="deck",
        candidate_deck_hash="deck",
        image="opm:test",
    )
    by_name = {check.name: check for check in checks}
    assert by_name["constraints_hash"].holds is False
    assert by_name["case_hash"].holds is True
    assert by_name["deck_hash"].holds is True
    assert by_name["opm_image"].holds is True


def test_both_sides_are_verified_under_one_case_and_one_image(
    tmp_path: Path, stub_tract: dict[str, Any]
) -> None:
    document = verification_run.compare_baseline_to_candidate(
        run_id="run-1",
        case_path=Path("config/cases/base.json"),
        constraints=CASE,
        baseline_schedule=BASELINE,
        candidate_schedule=CANDIDATE,
        control_dates=DATES,
        forecast=_forecast(1.0),
        runs_root=tmp_path,
        model_dir=tmp_path / "model",
        verifier=_verifier(stub_tract, {"baseline": 7.0e9, "candidate": 8.0e9}),
    )
    assert stub_tract["verify"] == 2
    assert stub_tract["decks"] == 2
    assert document["baseline"]["canonical_schedule_hash"] != (
        document["candidate"]["canonical_schedule_hash"]
    )
    assert document["conditions"]["deck_hash"] == "deck-template-hash"
    assert document["conditions"]["opm_image"]
    assert document["baseline"]["run_id"] != document["candidate"]["run_id"]
