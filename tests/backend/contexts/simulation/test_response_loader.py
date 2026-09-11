from __future__ import annotations

import struct
from pathlib import Path

import pytest

from backend.contexts.simulation.infrastructure.runner import OpmRunner
from backend.contexts.simulation.infrastructure.response_loader import (
    _ELEMENTS_PER_BLOCK,
    ResponseLoader,
    ResponseLoaderError,
    _build_interval_response,
    _build_state_at_date,
    _build_well_rows,
    _check_no_nan,
    _control_step_for_date,
    _fallback_control_mode,
    _find_artifact,
    _read_smspec,
    _read_unsmry_report_rows,
    _resolve_control_mode,
    _WellRow,
    load_density_by_pvtnum,
)
from backend.contexts.reservoir.infrastructure.summary import SummaryConnection, SummaryPlan
from backend.contexts.reservoir.domain.response import ActiveControlMode
from backend.contexts.schedule.domain.schedule import (
    ControlEvent,
    EventKind,
    N_INTERVALS,
    OperatingStatus,
    Schedule,
    ScheduleMeta,
)
from backend.contexts.runs.domain.run_result import RunResult, RunStatus, SummarySpec
from backend.contexts.reservoir.domain.response import N_DECK_DATES


from tests.support.backend.environment import (
    docker_unavailable_reason,
    missing_reason,
    model_z_dir,
)
from tests.support.backend.paths import DECKS_ROOT

pytestmark = [pytest.mark.slow, pytest.mark.opm]

DECKS = DECKS_ROOT

MODEL_Z = model_z_dir()

requires_model_z = pytest.mark.skipif(
    MODEL_Z is None, reason=missing_reason("Model_Z directory")
)

_PVT_WELLS = ("INJ", "MULTI", "PROD2")
_PVT_CONNECTIONS = (
    SummaryConnection(well="INJ", i=3, j=3, k=1, pvt_region=1),
    SummaryConnection(well="MULTI", i=2, j=2, k=1, pvt_region=1),
    SummaryConnection(well="MULTI", i=2, j=2, k=3, pvt_region=2),
    SummaryConnection(well="PROD2", i=1, j=1, k=1, pvt_region=1),
)
_PVT_DENSITY = {1: 800.0, 2: 850.0}
_EMPTY_SCHEDULE = Schedule(
    meta=ScheduleMeta(wells=(), provenance="test"),
    initial_state={},
    fixed_deck_events=(),
    control_events=(),
)


def require_docker() -> None:
    reason = docker_unavailable_reason()
    if reason is not None:
        pytest.skip(
            f"ResponseLoader acceptance on real artifacts requires OPM Flow; {reason}"
        )


def _run_deck(tmp_path: Path, name: str) -> RunResult:
    require_docker()
    runner = OpmRunner(tmp_path / "runs")
    result = runner.run_data_file(
        DECKS / name,
        deck_hash="d" * 64,
        canonical_schedule_hash="c" * 64,
        summary_hash="s" * 64,
    )
    assert result.status is RunStatus.OK, result.message
    return result




def test_read_smspec_and_unsmry_report_rows_real_mini(tmp_path: Path) -> None:

    result = _run_deck(tmp_path, "MINI.DATA")
    smspec_path = _find_artifact(result.artifacts, "SMSPEC")
    unsmry_path = _find_artifact(result.artifacts, "UNSMRY")

    smspec = _read_smspec(smspec_path)
    assert ("WBHP", "PROD", 0) in smspec.column
    assert ("WBHP", "INJ", 0) in smspec.column
    assert smspec.nx == 5 and smspec.ny == 5 and smspec.nz == 2

    rows = _read_unsmry_report_rows(unsmry_path, smspec.n_vectors)
    assert len(rows) == 10
    assert all(len(row) == smspec.n_vectors for row in rows)


def test_build_well_rows_reconstructs_oil_mass_across_pvt_regions_real(tmp_path: Path) -> None:

    result = _run_deck(tmp_path, "PVT.DATA")
    smspec_path = _find_artifact(result.artifacts, "SMSPEC")
    unsmry_path = _find_artifact(result.artifacts, "UNSMRY")
    smspec = _read_smspec(smspec_path)
    raw_rows = _read_unsmry_report_rows(unsmry_path, smspec.n_vectors)
    assert len(raw_rows) == 3

    plan = SummaryPlan(spec=SummarySpec(), wells=_PVT_WELLS, connections=_PVT_CONNECTIONS)
    well_rows = _build_well_rows(smspec, raw_rows, plan, _PVT_DENSITY)

    last = well_rows[-1]["MULTI"]
    copt_k1 = raw_rows[-1][smspec.column[("COPT", "MULTI", _nums(1, 1, smspec))]]
    copt_k3 = raw_rows[-1][smspec.column[("COPT", "MULTI", _nums(3, 1, smspec))]]
    assert copt_k1 > 0.0 and copt_k3 > 0.0

    correct = copt_k1 * 800.0 / 1000.0 + copt_k3 * 850.0 / 1000.0
    single_density_wrong = copt_k1 * 800.0 / 1000.0 + copt_k3 * 800.0 / 1000.0

    assert last.oil_mass_cum == pytest.approx(correct)
    assert last.oil_mass_cum != pytest.approx(single_density_wrong)

    assert _resolve_control_mode("MULTI", 0, well_rows[0]["MULTI"], {}) is ActiveControlMode.RATE_TARGET
    assert _resolve_control_mode("INJ", 0, well_rows[0]["INJ"], {}) is ActiveControlMode.RATE_TARGET
    assert (
        _resolve_control_mode("PROD2", 0, well_rows[0]["PROD2"], {}) is ActiveControlMode.BHP_LIMITED
    )
    assert _resolve_control_mode("PROD2", 2, well_rows[2]["PROD2"], {}) is ActiveControlMode.SHUT


def test_load_rejects_wrong_report_step_count_real(tmp_path: Path) -> None:

    result = _run_deck(tmp_path, "PVT.DATA")
    plan = SummaryPlan(spec=SummarySpec(), wells=_PVT_WELLS, connections=_PVT_CONNECTIONS)
    with pytest.raises(ResponseLoaderError, match="371"):
        ResponseLoader().load(result, plan, _EMPTY_SCHEDULE, _PVT_DENSITY)


@requires_model_z
def test_load_density_by_pvtnum_real_model_z() -> None:
    density = load_density_by_pvtnum(MODEL_Z)
    assert density == {
        1: pytest.approx(913.0765883224138),
        2: pytest.approx(928.1613457381528),
    }


def _nums(k: int, _unused: int, smspec) -> int:
    from backend.contexts.reservoir.infrastructure.summary import _grid_index

    return _grid_index(2, 2, k, smspec.nx, smspec.ny, smspec.nz) + 1




def _well_row(**overrides) -> _WellRow:
    base = dict(
        liquid_rate=0.0,
        injection_rate=0.0,
        oil_rate=0.0,
        thp=0.0,
        bhp=0.0,
        well_efficiency=1.0,
        liquid_cum=0.0,
        injection_cum=0.0,
        oil_mass_cum=0.0,
        wmctl=None,
    )
    base.update(overrides)
    return _WellRow(**base)


def test_state_at_date_axis_exact_371_and_well_order_stable() -> None:
    wells = ("W1", "W2")
    rows = [{well: _well_row(wmctl=4.0) for well in wells} for _ in range(N_DECK_DATES)]

    result = _build_state_at_date(rows, wells, _EMPTY_SCHEDULE)

    assert len(result) == N_DECK_DATES * len(wells)
    assert [state.well for state in result] == ["W1"] * N_DECK_DATES + ["W2"] * N_DECK_DATES
    assert {state.deck_date_index for state in result if state.well == "W1"} == set(
        range(N_DECK_DATES)
    )
    assert result[0].deck_date_index == 0
    assert result[N_DECK_DATES - 1].deck_date_index == N_DECK_DATES - 1


@pytest.mark.parametrize("wrong_length", [370, 372, 0])
def test_state_at_date_wrong_length_raises(wrong_length: int) -> None:
    rows = [{"W1": _well_row()} for _ in range(wrong_length)]
    with pytest.raises(ResponseLoaderError):
        _build_state_at_date(rows, ("W1",), _EMPTY_SCHEDULE)


def test_interval_response_axis_boundaries_and_per_well_isolation() -> None:

    wells = ("A", "B")
    rows = []
    for d in range(N_DECK_DATES):
        cumulative = float(d * d)
        rows.append(
            {
                "A": _well_row(
                    liquid_cum=cumulative,
                    oil_mass_cum=10.0 * cumulative,
                    injection_cum=100.0 * cumulative,
                ),
                "B": _well_row(
                    liquid_cum=1_000_000.0 + 2.0 * cumulative,
                    oil_mass_cum=2_000_000.0 + 20.0 * cumulative,
                    injection_cum=3_000_000.0 + 200.0 * cumulative,
                ),
            }
        )

    result = _build_interval_response(rows, wells)

    assert len(result) == N_INTERVALS * len(wells)
    assert max(r.control_step for r in result) == N_INTERVALS - 1
    assert min(r.control_step for r in result) == 0
    assert {r.control_step for r in result if r.well == "A"} == set(range(N_INTERVALS))

    by_key = {(r.control_step, r.well): r for r in result}
    for k in (0, 112, N_INTERVALS - 1):
        expected = float((147 + k) ** 2 - (146 + k) ** 2)
        response_a = by_key[(k, "A")]
        assert response_a.liquid_volume_delta == pytest.approx(expected)
        assert response_a.oil_mass_delta == pytest.approx(10.0 * expected)
        assert response_a.injection_volume_delta == pytest.approx(100.0 * expected)

        response_b = by_key[(k, "B")]
        assert response_b.liquid_volume_delta == pytest.approx(2.0 * expected)
        assert response_b.oil_mass_delta == pytest.approx(20.0 * expected)
        assert response_b.injection_volume_delta == pytest.approx(200.0 * expected)

    assert (N_INTERVALS - 1, "A") in by_key
    assert (N_INTERVALS, "A") not in by_key


@pytest.mark.parametrize("wrong_length", [370, 372, 0])
def test_interval_response_wrong_length_raises(wrong_length: int) -> None:
    rows = [{"W1": _well_row()} for _ in range(wrong_length)]
    with pytest.raises(ResponseLoaderError):
        _build_interval_response(rows, ("W1",))


def test_control_step_for_date_boundaries() -> None:
    assert _control_step_for_date(0) is None
    assert _control_step_for_date(145) is None
    assert _control_step_for_date(146) == -1
    assert _control_step_for_date(147) == 0
    assert _control_step_for_date(370) == N_INTERVALS - 1


@pytest.mark.parametrize(
    "code,expected",
    [
        (1, ActiveControlMode.RATE_TARGET),
        (2, ActiveControlMode.RATE_TARGET),
        (3, ActiveControlMode.RATE_TARGET),
        (4, ActiveControlMode.RATE_TARGET),
        (5, ActiveControlMode.RATE_TARGET),
        (9, ActiveControlMode.RATE_TARGET),
        (6, ActiveControlMode.BHP_LIMITED),
        (7, ActiveControlMode.BHP_LIMITED),
        (-1, ActiveControlMode.RATE_TARGET),
        (-10, ActiveControlMode.UNKNOWN),
        (42, ActiveControlMode.UNKNOWN),
    ],
)
def test_resolve_control_mode_wmctl_codes(code: int, expected: ActiveControlMode) -> None:
    row = _well_row(wmctl=float(code))
    assert _resolve_control_mode("W", 200, row, {}) is expected


def test_resolve_control_mode_wmctl_zero_not_commissioned_then_shut() -> None:
    schedule = Schedule(
        meta=ScheduleMeta(wells=("W",), provenance="test"),
        initial_state={},
        fixed_deck_events=(),
        control_events=(ControlEvent(control_step=60, well="W", kind=EventKind.OPEN),),
    )
    from backend.contexts.simulation.infrastructure.response_loader import build_well_timelines

    timelines = build_well_timelines(schedule)
    row = _well_row(wmctl=0.0)

    assert _resolve_control_mode("W", 200, row, timelines) is ActiveControlMode.NOT_COMMISSIONED
    assert _resolve_control_mode("W", 250, row, timelines) is ActiveControlMode.SHUT
    assert _resolve_control_mode("W", 50, row, timelines) is ActiveControlMode.SHUT


@pytest.mark.parametrize(
    "kwargs,expected",
    [
        (dict(commissioned=False, operating_status=OperatingStatus.SHUT, setpoint=0.0,
              liquid_rate=0.0, injection_rate=0.0, bhp=0.0), ActiveControlMode.NOT_COMMISSIONED),
        (dict(commissioned=True, operating_status=OperatingStatus.SHUT, setpoint=50.0,
              liquid_rate=0.0, injection_rate=0.0, bhp=0.0), ActiveControlMode.SHUT),
        (dict(commissioned=True, operating_status=OperatingStatus.OPEN, setpoint=0.0,
              liquid_rate=0.0, injection_rate=0.0, bhp=100.0), ActiveControlMode.UNKNOWN),
        (dict(commissioned=True, operating_status=OperatingStatus.OPEN, setpoint=100.0,
              liquid_rate=99.95, injection_rate=0.0, bhp=100.0), ActiveControlMode.RATE_TARGET),
        (dict(commissioned=True, operating_status=OperatingStatus.OPEN, setpoint=100.0,
              liquid_rate=50.0, injection_rate=0.0, bhp=50.5), ActiveControlMode.BHP_LIMITED),
        (dict(commissioned=True, operating_status=OperatingStatus.OPEN, setpoint=100.0,
              liquid_rate=50.0, injection_rate=0.0, bhp=150.0), ActiveControlMode.RATE_TARGET),
        (dict(commissioned=True, operating_status=OperatingStatus.OPEN, setpoint=100.0,
              liquid_rate=0.0, injection_rate=50.0, bhp=298.0), ActiveControlMode.BHP_LIMITED),
    ],
)
def test_fallback_control_mode(kwargs: dict, expected: ActiveControlMode) -> None:
    assert _fallback_control_mode(**kwargs) is expected


def test_find_artifact_requires_exactly_one_match() -> None:
    with pytest.raises(ResponseLoaderError):
        _find_artifact([], "SMSPEC")
    with pytest.raises(ResponseLoaderError):
        _find_artifact(["a.SMSPEC", "b.SMSPEC"], "SMSPEC")
    assert _find_artifact(["a.UNSMRY", "a.SMSPEC"], "UNSMRY") == Path("a.UNSMRY")


def test_load_rejects_non_ok_run_result() -> None:
    run_result = RunResult(
        run_id="r",
        status=RunStatus.NOT_CONVERGED,
        deck_hash="d" * 64,
        canonical_schedule_hash="c" * 64,
        summary_hash="s" * 64,
        artifacts=(),
        wallclock_seconds=1.0,
        message="did not converge",
    )
    plan = SummaryPlan(spec=SummarySpec(), wells=(), connections=())
    with pytest.raises(ResponseLoaderError):
        ResponseLoader().load(run_result, plan, _EMPTY_SCHEDULE, {})




def _pack_record(payload: bytes) -> bytes:
    length = struct.pack(">I", len(payload))
    return length + payload + length


def _pack_data(arr_type: str, values: list) -> bytes:
    max_n = _ELEMENTS_PER_BLOCK[arr_type]
    out = bytearray()
    for start in range(0, len(values), max_n):
        chunk = values[start : start + max_n]
        n = len(chunk)
        if arr_type == "CHAR":
            payload = b"".join(str(v).encode("ascii").ljust(8)[:8] for v in chunk)
        elif arr_type == "INTE":
            payload = struct.pack(f">{n}i", *chunk)
        elif arr_type == "REAL":
            payload = struct.pack(f">{n}f", *chunk)
        else:
            raise ValueError(arr_type)
        out += _pack_record(payload)
    return bytes(out)


def _write_keyword_file(path: Path, blocks: list) -> None:
    with path.open("wb") as handle:
        for keyword, arr_type, values in blocks:
            header = keyword.ljust(8).encode("ascii")[:8] + struct.pack(">I", len(values)) + arr_type.encode("ascii")
            handle.write(_pack_record(header))
            handle.write(_pack_data(arr_type, values))


def _fabricate_smspec(path: Path) -> None:
    keywords = ["WLPR", "WWIR", "WBHP", "WTHP", "WEFF", "WLPT", "WWIT", "WMCTL", "COPT", "COPR"]
    wgnames = ["W1"] * 8 + ["W1", "W1"]
    nums = [0] * 8 + [1, 1]
    _write_keyword_file(
        path,
        [
            ("DIMENS", "INTE", [len(keywords), 1, 1, 1, 0, 0]),
            ("KEYWORDS", "CHAR", keywords),
            ("WGNAMES", "CHAR", wgnames),
            ("NUMS", "INTE", nums),
        ],
    )


def _fabricate_unsmry(path: Path, report_rows: list[list[float]]) -> None:
    blocks = []
    for index, values in enumerate(report_rows):
        blocks.append(("SEQHDR", "INTE", [index]))
        blocks.append(("MINISTEP", "INTE", [index]))
        blocks.append(("PARAMS", "REAL", values))
    _write_keyword_file(path, blocks)


def _synthetic_run_result(tmp_path: Path, *, inject_nan_at: int | None = None) -> RunResult:
    smspec_path = tmp_path / "SYN.SMSPEC"
    unsmry_path = tmp_path / "SYN.UNSMRY"
    _fabricate_smspec(smspec_path)

    rows: list[list[float]] = []
    for d in range(N_DECK_DATES):
        bhp = float("nan") if d == inject_nan_at else 120.0
        rows.append(
            [
                5.0,
                0.0,
                bhp,
                30.0,
                1.0,
                float(d),
                0.0,
                4.0,
                float(d) * 2.0,
                5.0,
            ]
        )
    _fabricate_unsmry(unsmry_path, rows)

    return RunResult(
        run_id="synthetic-run",
        status=RunStatus.OK,
        deck_hash="d" * 64,
        canonical_schedule_hash="c" * 64,
        summary_hash="s" * 64,
        artifacts=(str(smspec_path), str(unsmry_path)),
        wallclock_seconds=0.01,
        message="synthetic fixture - shape/bounds, not physics",
    )


def _synthetic_plan() -> SummaryPlan:
    return SummaryPlan(
        spec=SummarySpec(),
        wells=("W1",),
        connections=(SummaryConnection(well="W1", i=1, j=1, k=1, pvt_region=1),),
    )


def test_load_end_to_end_synthetic_axes_hash_and_control_mode(tmp_path: Path) -> None:
    run_result = _synthetic_run_result(tmp_path)
    plan = _synthetic_plan()
    density = {1: 900.0}

    artifact = ResponseLoader().load(run_result, plan, _EMPTY_SCHEDULE, density)

    assert artifact.source_run_id == "synthetic-run"
    assert len(artifact.state_at_date) == N_DECK_DATES
    assert len(artifact.interval_response) == N_INTERVALS
    assert {s.deck_date_index for s in artifact.state_at_date} == set(range(N_DECK_DATES))
    assert {r.control_step for r in artifact.interval_response} == set(range(N_INTERVALS))
    assert all(s.active_control_mode is ActiveControlMode.RATE_TARGET for s in artifact.state_at_date)
    assert all(r.liquid_volume_delta == pytest.approx(1.0) for r in artifact.interval_response)
    assert all(r.oil_mass_delta == pytest.approx(1.8) for r in artifact.interval_response)

    artifact_again = ResponseLoader().load(run_result, plan, _EMPTY_SCHEDULE, density)
    assert artifact_again.response_hash == artifact.response_hash


def test_load_rejects_nan(tmp_path: Path) -> None:
    run_result = _synthetic_run_result(tmp_path, inject_nan_at=200)
    plan = _synthetic_plan()
    with pytest.raises(ResponseLoaderError, match="NaN"):
        ResponseLoader().load(run_result, plan, _EMPTY_SCHEDULE, {1: 900.0})


def test_check_no_nan_accepts_clean_data() -> None:
    rows = [{"W1": _well_row(wmctl=4.0)} for _ in range(N_DECK_DATES)]
    state = _build_state_at_date(rows, ("W1",), _EMPTY_SCHEDULE)
    interval = _build_interval_response(rows, ("W1",))
    _check_no_nan(state, interval)


@pytest.mark.parametrize('operator,args,expected_status,target', [
    ('WCONPROD', ('OPEN', 'LRAT', '1*', '1*', '1*', '120'), OperatingStatus.OPEN, 120.),
    ('WCONINJE', ('WATER', 'SHUT', 'RATE', '80'), OperatingStatus.SHUT, 80.),
])
def test_fixed_commissioning_controls_availability_status_and_target(operator, args, expected_status, target):
    from backend.contexts.schedule.domain.schedule import FixedDeckEvent
    from backend.contexts.simulation.infrastructure.response_loader import build_well_timelines
    schedule = Schedule(
        meta=ScheduleMeta(wells=('NEW',)), initial_state={},
        fixed_deck_events=(FixedDeckEvent(14, 'NEW', operator, args),),
        control_events=(),
    )
    timeline = build_well_timelines(schedule)['NEW']
    assert not timeline.is_commissioned(13)
    assert timeline.is_commissioned(14)
    assert timeline.operating_status(14) is expected_status
    assert timeline.setpoint(14) == target


def test_managed_controls_override_fixed_commissioning_at_same_step():
    from backend.contexts.schedule.domain.schedule import FixedDeckEvent
    from backend.contexts.simulation.infrastructure.response_loader import build_well_timelines
    schedule = Schedule(
        meta=ScheduleMeta(wells=('NEW',)), initial_state={},
        fixed_deck_events=(FixedDeckEvent(14, 'NEW', 'WCONPROD', ('OPEN', 'LRAT', '1*', '1*', '1*', '120')),),
        control_events=(
            ControlEvent(14, 'NEW', EventKind.SET_RATE, 80.),
            ControlEvent(14, 'NEW', EventKind.CONVERT_INJ),
            ControlEvent(14, 'NEW', EventKind.SET_LRAT, 0.),
            ControlEvent(14, 'NEW', EventKind.SHUT),
        ),
    )
    timeline = build_well_timelines(schedule)['NEW']
    assert timeline.is_commissioned(14)
    assert timeline.operating_status(14) is OperatingStatus.SHUT
    assert timeline.setpoint(14) == 80.
