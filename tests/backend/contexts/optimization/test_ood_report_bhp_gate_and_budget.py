from __future__ import annotations

import ast
import json
import math
from pathlib import Path
from types import SimpleNamespace

import pytest

from backend.contexts.optimization.application.search_use_case import (
    BhpTolerance,
    BhpToleranceError,
    OpmBudgetError,
    RunBudget,
    SURROGATE_METRICS_FORMAT,
    _bhp_tolerance_decision,
    bhp_exceedance_bar,
    candidate_card,
    read_opm_budget,
    surrogate_blocking_violations,
)
from backend.contexts.optimization.application.environment import (
    OOD_EXCEEDANCE_LIMIT,
    SELF_REFERENCE_SKIP_REASON,
    OutOfDomainScheduleError,
    exceedance_record,
    format_ood_exceedances,
)
from backend.core.contracts import Constraints
from backend.contexts.constraints.domain.constraints import (
    BHP_INJECTOR_MAX_BAR,
    BHP_PRODUCER_MIN_BAR,
)
from backend.domain.schedule import ViolationKind
from backend.contexts.schedule.domain.validate import Violation
from backend.contexts.robustness.domain.ood import Exceedance, OodScore
from backend.interfaces.cli.surrogate import check as _check
from backend.contexts.optimization.application import environment as _src_environment
from backend.contexts.optimization.application import search_use_case as _src_search_use_case

CHECK_SOURCE = Path(_check.__file__)


def _exceedance(feature: str, well: str, step: int, score: float) -> Exceedance:
    return Exceedance(
        feature=feature,
        well=well,
        control_step=step,
        value=1000.0 + score,
        low=0.0,
        high=100.0,
        score=score,
    )


def _ood(count: int) -> OodScore:
    items = tuple(
        _exceedance(f"feature_{index}", f"W{index}", index, float(count - index))
        for index in range(count)
    )
    return OodScore(
        score=items[0].score if items else 0.0,
        exceedances=items,
        n_nodes=max(1, count),
    )


def test_rejected_candidate_carries_top_five_exceedances_with_feature_and_range() -> None:
    report = format_ood_exceedances(_ood(9))

    assert len(report) == OOD_EXCEEDANCE_LIMIT == 5
    assert [item["feature"] for item in report] == [
        "feature_0",
        "feature_1",
        "feature_2",
        "feature_3",
        "feature_4",
    ]
    for item in report:
        assert set(item) == {
            "feature",
            "well",
            "control_step",
            "value",
            "train_low",
            "train_high",
            "score",
            "unbounded",
        }
        assert item["train_low"] == 0.0
        assert item["train_high"] == 100.0
        assert item["well"].startswith("W")
        assert isinstance(item["control_step"], int)
    assert [item["score"] for item in report] == sorted(
        (item["score"] for item in report), reverse=True
    )


def test_a_candidate_inside_the_domain_reports_no_exceedances() -> None:
    assert format_ood_exceedances(OodScore(score=0.0, exceedances=(), n_nodes=7)) == ()


def test_an_unseen_category_is_reported_as_unbounded_not_as_a_number() -> None:
    record = exceedance_record(
        Exceedance(
            feature="availability",
            well="P17",
            control_step=42,
            value=math.nan,
            low=math.nan,
            high=math.nan,
            score=math.inf,
        )
    )

    assert record["unbounded"] is True
    assert record["score"] is None
    assert record["value"] is None
    assert record["train_low"] is None and record["train_high"] is None
    assert json.dumps(record, allow_nan=False)


def test_the_rejection_error_carries_the_exceedance_list() -> None:
    error = OutOfDomainScheduleError(3.5, "worst", format_ood_exceedances(_ood(6)))

    assert len(error.exceedances) == 5
    assert error.exceedances[0]["feature"] == "feature_0"
    assert error.score == 3.5


def test_the_two_argument_rejection_still_works() -> None:
    error = OutOfDomainScheduleError(9.0, "outside training")

    assert error.exceedances == ()


def test_the_candidate_card_of_a_rejected_plan_shows_which_feature_left_the_domain() -> None:
    card = candidate_card(
        schedule_hash="",
        theta={},
        npv_predicted=None,
        npv_parts={},
        ood_score=4.0,
        ood_worst="feature_0@W0:0",
        scenario_ood=0.9,
        physics={},
        static_violations=None,
        dynamic_blocking_violations=None,
        feasible=False,
        violations=[{"scenario_id": "surrogate-domain", "regret": 1.0, "what": "x"}],
        strategy="cma-es",
        ood_exceedances=format_ood_exceedances(_ood(7)),
    )

    assert len(card["ood_exceedances"]) == 5
    first = card["ood_exceedances"][0]
    assert first["feature"] == "feature_0"
    assert (first["train_low"], first["train_high"]) == (0.0, 100.0)
    assert json.dumps(card, ensure_ascii=False, allow_nan=False)


def test_a_card_without_exceedances_still_names_the_field() -> None:
    card = candidate_card(
        schedule_hash="h",
        theta={},
        npv_predicted=1.0,
        npv_parts={},
        ood_score=0.0,
        ood_worst=None,
        scenario_ood=None,
        physics={"complete": 1, "admissible": 1},
        static_violations=0,
        dynamic_blocking_violations=0,
        feasible=True,
        violations=[],
        strategy="finalist",
    )

    assert card["ood_exceedances"] == []


def _check_source() -> ast.Module:
    return ast.parse(CHECK_SOURCE.read_text(encoding="utf-8"))


def _check_function(name: str) -> ast.FunctionDef:
    for node in _check_source().body:
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return node
    raise AssertionError(f"функция {name} не найдена")


def _check_constant(name: str) -> str:
    for node in _check_source().body:
        if (
            isinstance(node, ast.Assign)
            and isinstance(node.targets[0], ast.Name)
            and node.targets[0].id == name
        ):
            return ast.literal_eval(node.value)
    raise AssertionError(f"константа {name} не найдена")


def test_surrogate_check_turns_the_physics_gate_off_instead_of_falling_over() -> None:
    source = ast.unparse(_check_function("check"))

    assert "physics_gate=False" in source
    assert "physics_gate_reason" in source


def test_the_report_says_the_differential_invariants_were_not_checked_and_why() -> None:
    note = _check_constant("BASE_PHYSICS_GATE_NOTE")

    assert "INJECTION_RESPONSE" in note
    assert "MATERIAL_BALANCE" in note
    assert "опора" in note
    assert "не определён" in note or "не определены" in note


def test_the_skip_reason_of_the_self_reference_names_the_cause() -> None:
    assert "одно расписание" in SELF_REFERENCE_SKIP_REASON
    assert "не нарушен" in SELF_REFERENCE_SKIP_REASON


def _optimization_context_source() -> str:
    context_root = Path(_src_environment.__file__).parent.parent
    return chr(10).join(
        path.read_text(encoding="utf-8")
        for path in sorted(context_root.rglob("*.py"))
        if "__pycache__" not in path.parts
    )


def test_the_self_reference_skip_is_only_for_the_diagnostic_gate_off_mode() -> None:
    search_source = _optimization_context_source()

    assert 'and not getattr(env, "physics_gate", True)' in search_source
    assert "MissingReferenceError.SELF_REFERENCE" in search_source


def test_the_prediction_block_reports_which_invariants_were_not_checked() -> None:
    source = ast.unparse(_check_function("_prediction_block"))

    assert "invariants_not_checked" in source
    assert "invariants_skip_reasons" in source
    assert "differential_invariants_checked" in source
    assert "ood_exceedances" in source


def test_surrogate_check_accepts_a_case_and_reports_two_predictions() -> None:
    parser = ast.unparse(_check_function("main"))
    check = ast.unparse(_check_function("check"))

    assert "'--case'" in parser or '"--case"' in parser
    assert "case_path=args.case" in parser
    assert "payload['predictions']['case']" in check
    assert "'base': base" in check or '"base": base' in check


def _bhp(kind: ViolationKind, value: float) -> Violation:
    return Violation(kind=kind, control_step=3, well="P1", value=value, detail="d")


def _case(producer_min: float, injector_max: float) -> Constraints:
    return Constraints(
        infrastructure={
            BHP_PRODUCER_MIN_BAR: producer_min,
            BHP_INJECTOR_MAX_BAR: injector_max,
        }
    )


def _measured(delta: float) -> BhpTolerance:
    return BhpTolerance(
        delta_bar=delta,
        origin="metrics-report-p95",
        source="report.json",
        n_states=1000,
        detail="δ измерена",
    )


UNMEASURED = BhpTolerance(
    delta_bar=None,
    origin="unmeasured-report-absent",
    source="none",
    n_states=0,
    detail="отчёт не считался",
)


def test_bhp_beyond_the_limit_by_more_than_delta_is_blocking() -> None:
    constraints = _case(50.0, 300.0)
    far = _bhp(ViolationKind.BHP_BELOW_PRODUCER_LIMIT, 40.0)

    assert bhp_exceedance_bar(far, constraints) == pytest.approx(10.0)
    assert surrogate_blocking_violations((far,), constraints, _measured(5.0)) == (far,)


def test_bhp_within_delta_of_the_limit_passes() -> None:
    constraints = _case(50.0, 300.0)
    near = _bhp(ViolationKind.BHP_BELOW_PRODUCER_LIMIT, 46.0)

    assert bhp_exceedance_bar(near, constraints) == pytest.approx(4.0)
    assert surrogate_blocking_violations((near,), constraints, _measured(5.0)) == ()


def test_the_injector_side_uses_the_upper_limit() -> None:
    constraints = _case(50.0, 300.0)
    far = _bhp(ViolationKind.BHP_ABOVE_INJECTOR_LIMIT, 320.0)
    near = _bhp(ViolationKind.BHP_ABOVE_INJECTOR_LIMIT, 302.0)

    assert bhp_exceedance_bar(far, constraints) == pytest.approx(20.0)
    assert surrogate_blocking_violations(
        (far, near), constraints, _measured(5.0)
    ) == (far,)


def test_exactly_delta_is_not_beyond_delta() -> None:
    constraints = _case(50.0, 300.0)
    edge = _bhp(ViolationKind.BHP_BELOW_PRODUCER_LIMIT, 45.0)

    assert surrogate_blocking_violations((edge,), constraints, _measured(5.0)) == ()


def test_a_bhp_violation_without_a_measured_pressure_is_an_error_not_a_pass() -> None:
    with pytest.raises(BhpToleranceError, match="забойного давления"):
        bhp_exceedance_bar(
            _bhp(ViolationKind.BHP_BELOW_PRODUCER_LIMIT, math.nan), _case(50.0, 300.0)
        )


def test_a_non_bhp_kind_is_refused_by_the_tolerance_helper() -> None:
    with pytest.raises(BhpToleranceError, match="не нарушение канала BHP"):
        bhp_exceedance_bar(
            _bhp(ViolationKind.LRAT_ABOVE_CEILING, 10.0), _case(50.0, 300.0)
        )


def test_non_bhp_violations_are_never_filtered_by_the_bhp_gate() -> None:
    constraints = _case(50.0, 300.0)
    other = _bhp(ViolationKind.LRAT_ABOVE_CEILING, 10.0)

    assert surrogate_blocking_violations((other,), constraints, _measured(5.0)) == (
        other,
    )
    assert surrogate_blocking_violations((other,), constraints, UNMEASURED) == (other,)


def test_without_delta_the_previous_behaviour_stands_and_is_marked_in_provenance() -> None:
    constraints = _case(50.0, 300.0)
    far = _bhp(ViolationKind.BHP_BELOW_PRODUCER_LIMIT, 1.0)

    assert surrogate_blocking_violations((far,), constraints, UNMEASURED) == ()
    provenance = UNMEASURED.as_provenance()
    assert provenance["bhp_gate_delta_bar"] == "unmeasured"
    assert (
        provenance["bhp_gate_agreement"]
        == "documented-difference-search-lets-bhp-through"
    )


def test_measured_delta_declares_the_gates_agree() -> None:
    provenance = _measured(3.25).as_provenance()

    assert provenance["bhp_gate_delta_bar"] == repr(3.25)
    assert provenance["bhp_gate_agreement"] == "same-definition-as-submission"
    assert provenance["bhp_gate_delta_states"] == "1000"


def _metrics(tmp_path: Path, channel: dict) -> Path:
    path = tmp_path / "surrogate-metrics.json"
    path.write_text(
        json.dumps(
            {
                "format": SURROGATE_METRICS_FORMAT,
                "optimizer_manifold": {"bhp_channel": channel},
            }
        ),
        encoding="utf-8",
    )
    return path


def test_delta_is_read_from_the_metrics_report(tmp_path: Path) -> None:
    path = _metrics(
        tmp_path,
        {"channel": "bhp", "bhp_error_bar_p95": 7.5, "n_states": 2240},
    )

    decision = _bhp_tolerance_decision({"AIOS_SURROGATE_METRICS_PATH": str(path)})

    assert decision.delta_bar == 7.5
    assert decision.n_states == 2240
    assert decision.origin == "metrics-report-p95"
    assert decision.measured


def test_an_absent_report_leaves_delta_unmeasured_and_says_so(tmp_path: Path) -> None:
    decision = _bhp_tolerance_decision({"AIOS_PROJECT_ROOT": str(tmp_path)})

    assert decision.delta_bar is None
    assert decision.origin == "unmeasured-report-absent"
    assert "придумывать" in decision.detail


def test_a_declared_report_that_is_absent_is_an_error_not_a_silent_default(
    tmp_path: Path,
) -> None:
    with pytest.raises(BhpToleranceError, match="отсутствующий"):
        _bhp_tolerance_decision(
            {"AIOS_SURROGATE_METRICS_PATH": str(tmp_path / "absent.json")}
        )


def test_a_report_without_an_opm_response_leaves_delta_unmeasured(
    tmp_path: Path,
) -> None:
    path = _metrics(tmp_path, {"channel": "bhp", "unavailable": "нет отклика OPM"})

    decision = _bhp_tolerance_decision({"AIOS_SURROGATE_METRICS_PATH": str(path)})

    assert decision.delta_bar is None
    assert decision.origin == "unmeasured-no-opm-response"


def test_a_report_with_a_non_numeric_p95_is_an_error(tmp_path: Path) -> None:
    path = _metrics(tmp_path, {"channel": "bhp", "bhp_error_bar_p95": "много"})

    with pytest.raises(BhpToleranceError, match="не число"):
        _bhp_tolerance_decision({"AIOS_SURROGATE_METRICS_PATH": str(path)})


def test_a_report_with_no_measured_state_is_an_error(tmp_path: Path) -> None:
    path = _metrics(
        tmp_path, {"channel": "bhp", "bhp_error_bar_p95": 3.0, "n_states": 0}
    )

    with pytest.raises(BhpToleranceError, match="без единого измеренного состояния"):
        _bhp_tolerance_decision({"AIOS_SURROGATE_METRICS_PATH": str(path)})


def test_the_operator_can_override_delta(tmp_path: Path) -> None:
    decision = _bhp_tolerance_decision(
        {"AIOS_BHP_GATE_DELTA_BAR": "2.5", "AIOS_PROJECT_ROOT": str(tmp_path)}
    )

    assert decision.delta_bar == 2.5
    assert decision.origin == "environment-override"


def test_a_negative_override_is_refused(tmp_path: Path) -> None:
    with pytest.raises(BhpToleranceError, match="неотрицательным"):
        _bhp_tolerance_decision(
            {"AIOS_BHP_GATE_DELTA_BAR": "-1", "AIOS_PROJECT_ROOT": str(tmp_path)}
        )


def _journal(tmp_path: Path, entries: list[dict]) -> Path:
    path = tmp_path / "opm-budget.jsonl"
    path.write_text(
        "".join(json.dumps(entry, sort_keys=True) + "\n" for entry in entries),
        encoding="utf-8",
    )
    return path


def test_the_opm_run_count_comes_from_the_budget_journal(tmp_path: Path) -> None:
    path = _journal(
        tmp_path,
        [
            {"run_id": "a", "wallclock_seconds": 1200.0, "status": "OK"},
            {"run_id": "b", "wallclock_seconds": 900.0, "status": "FAILED"},
        ],
    )

    runs, seconds, lines = read_opm_budget(path)

    assert runs == 2
    assert seconds == pytest.approx(2100.0)
    assert lines == 2


def test_only_the_runs_after_the_mark_are_counted(tmp_path: Path) -> None:
    path = _journal(
        tmp_path,
        [
            {"run_id": "old", "wallclock_seconds": 10.0},
            {"run_id": "new", "wallclock_seconds": 20.0},
            {"run_id": "newer", "wallclock_seconds": 30.0},
        ],
    )

    runs, seconds, _ = read_opm_budget(path, since_line=1)

    assert runs == 2
    assert seconds == pytest.approx(50.0)


def test_a_missing_journal_means_zero_runs_not_a_crash(tmp_path: Path) -> None:
    assert read_opm_budget(tmp_path / "absent.jsonl") == (0, None, 0)


def test_a_run_without_a_recorded_wallclock_leaves_the_sum_unmeasured(
    tmp_path: Path,
) -> None:
    path = _journal(tmp_path, [{"run_id": "a", "wallclock_seconds": None}])

    runs, seconds, _ = read_opm_budget(path)

    assert runs == 1
    assert seconds is None


def test_a_broken_journal_line_is_an_error_not_a_skipped_run(tmp_path: Path) -> None:
    path = tmp_path / "opm-budget.jsonl"
    path.write_text('{"run_id": "a"}\nnot json\n', encoding="utf-8")

    with pytest.raises(OpmBudgetError, match="не разбирается"):
        read_opm_budget(path)


def test_a_journal_entry_without_a_run_id_is_an_error(tmp_path: Path) -> None:
    path = _journal(tmp_path, [{"status": "OK"}])

    with pytest.raises(OpmBudgetError, match="без run_id"):
        read_opm_budget(path)


def test_time_and_run_counts_reach_the_manifest() -> None:
    measured = RunBudget(
        wallclock_seconds=3612.5,
        surrogate_evaluations=120,
        opm_runs=4,
        opm_runs_source="out/opm-budget.jsonl",
        opm_wallclock_seconds=4800.0,
    )

    document = measured.as_dict()

    assert document == {
        "wallclock_seconds": 3612.5,
        "surrogate_evaluations": 120,
        "opm_runs": 4,
        "opm_runs_source": "out/opm-budget.jsonl",
        "opm_wallclock_seconds": 4800.0,
    }
    assert measured.as_provenance()["run_opm_runs"] == "4"
    assert measured.as_provenance()["run_surrogate_evaluations"] == "120"


def test_an_unmeasured_opm_wallclock_is_marked_not_zeroed() -> None:
    measured = RunBudget(
        wallclock_seconds=1.0,
        surrogate_evaluations=1,
        opm_runs=1,
        opm_runs_source="j",
        opm_wallclock_seconds=None,
    )

    assert measured.as_dict()["opm_wallclock_seconds"] is None
    assert measured.as_provenance()["run_opm_wallclock_seconds"] == "unrecorded"


def _run_source() -> ast.Module:
    return ast.parse(
        (Path(_src_search_use_case.__file__)).read_text(
            encoding="utf-8"
        )
    )


def _run_function(name: str) -> ast.FunctionDef:
    for node in _run_source().body:
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return node
    raise AssertionError(f"функция {name} не найдена")


def test_the_search_measures_its_own_wallclock_and_reads_the_journal() -> None:
    source = ast.unparse(_run_function("run_search"))
    start = ast.unparse(_run_function("start_run_clock"))
    close = ast.unparse(_run_function("close_run_clock"))
    measure = ast.unparse(_run_function("measure_run_budget"))

    assert "start_run_clock()" in source
    assert "close_run_clock(report.evaluations)" in source
    assert "time.monotonic()" in start and "_journal_line_count(journal)" in start
    assert "time.monotonic() - started" in close
    assert "read_opm_budget" in measure


def test_a_run_clock_that_was_never_started_is_an_error_not_a_zero() -> None:
    import backend.contexts.optimization.application.search_use_case as module

    saved = dict(module.RUN_CLOCK)
    module.RUN_CLOCK.update({"journal": None, "mark": 0, "started": None})
    try:
        with pytest.raises(OpmBudgetError, match="не начат"):
            module.close_run_clock(5)
    finally:
        module.RUN_CLOCK.update(saved)


def test_the_run_clock_measures_a_real_interval(tmp_path: Path) -> None:
    import backend.contexts.optimization.application.search_use_case as module

    journal = _journal(tmp_path, [{"run_id": "a", "wallclock_seconds": 60.0}])
    saved = dict(module.RUN_CLOCK)
    module.RUN_CLOCK.update({"journal": journal, "mark": 0, "started": 0.0})
    try:
        measured = module.close_run_clock(42)
    finally:
        module.RUN_CLOCK.update(saved)

    assert measured.opm_runs == 1
    assert measured.surrogate_evaluations == 42
    assert measured.wallclock_seconds > 0.0
    assert measured.opm_wallclock_seconds == pytest.approx(60.0)


def test_the_manifest_writer_names_every_budget_field() -> None:
    source = ast.unparse(_run_function("main"))

    for name in (
        "wallclock_seconds",
        "surrogate_evaluations",
        "opm_runs",
        "opm_wallclock_seconds",
    ):
        assert name in source


def test_the_search_does_not_keep_a_second_opm_counter() -> None:
    measure = _run_function("measure_run_budget")
    assignments = {
        ast.unparse(node.value)
        for node in ast.walk(measure)
        if isinstance(node, ast.keyword) and node.arg == "opm_runs"
    }

    assert assignments == {"int(opm_runs)"}
    assert ast.unparse(measure).count("read_opm_budget") == 1
    assert "read_opm_budget" not in ast.unparse(_run_function("run_search"))


def test_the_bhp_gate_is_used_in_both_search_paths() -> None:
    baseline = ast.unparse(_run_function("_search_near_baseline"))
    core = ast.unparse(_run_function("run_search"))

    assert "surrogate_blocking_violations" in baseline
    assert "surrogate_blocking_violations" in core
    assert "bhp_tolerance.as_provenance()" in core


def test_the_evaluator_publishes_the_exceedance_list() -> None:
    search_source = _optimization_context_source()

    assert "evaluator.ood_exceedances = format_ood_exceedances(" in search_source
    assert "self.exceedances = tuple(dict(item) for item in exceedances)" in search_source


def test_no_comments_in_the_touched_files() -> None:
    for path in (
        Path(_src_search_use_case.__file__),
        Path(_src_environment.__file__),
        CHECK_SOURCE,
    ):
        for number, line in enumerate(
            path.read_text(encoding="utf-8").splitlines(), start=1
        ):
            stripped = line.strip()
            if not stripped.startswith("#"):
                continue
            assert stripped.startswith(
                ("# type: ignore", "# noqa", "# pragma: no cover")
            ), f"{path.name}:{number}: {stripped}"
