from __future__ import annotations

import json
import math
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest

from aios_backend.core.contracts import (
    ControlEvent,
    EventKind,
    FixedDeckEvent,
    N_CONTROL_DATES,
    RunArtifact,
    T0,
)
from aios_backend.core.contracts.response import N_DECK_DATES
from aios_backend.presentation.ui_export.artifact_io import load_bundle
from aios_backend.presentation.ui_export.base_artifact import DEFAULT_RESPONSE_PATH, REAL_PROVENANCE
from aios_backend.presentation.ui_export.deck import load_wellheads
from aios_backend.presentation.ui_export.demo import (
    _DEFAULT_DENSITY,
    BASE_ID,
    TARGET_TOTAL_MS,
    WHATIF_ID,
    build_demo,
    build_demo_script,
    deck_scale,
    demo_meta,
    export_demo_script_json,
    field_events,
)
from aios_backend.presentation.ui_export.demo_artifact import DEMO_PROVENANCE, DEMO_SEED, build_demo_artifact
from aios_backend.presentation.ui_export.fixtures import make_synthetic_artifact
from aios_backend.presentation.ui_export.graph_view import build_lambda_graph
from aios_backend.presentation.ui_export.npv_view import build_npv_by_well
from aios_backend.presentation.ui_export.scenarios import build_scenario_index
from aios_backend.presentation.ui_export.timeline import build_timeline, build_trace
from aios_backend.presentation.ui_export.webdata import DEFAULT_DECK_PATH

from conftest import missing_reason

VIEW_FILES = (
    "timeline.json",
    "graph.json",
    "npv.json",
    "trace.json",
    "hierarchy.json",
    "ablation.json",
)
REAL_VIEW_FILES = ("timeline.json", "graph.json", "npv.json", "trace.json")
ROOT_FILES = ("scenarios.json", "wells.json", "demo-script.json")
EVENT_TYPES = ("COMMISSIONED", "ROLE_CHANGE", "SHUT", "RULE_FIRED", "MORPH")

# Сборка витрины требует отклика настоящего прогона; сам документ ролика
# и разбор событий от него не зависят и проверяются на фикстуре ниже.
needs_base_run = pytest.mark.skipif(
    not DEFAULT_RESPONSE_PATH.is_file(),
    reason=missing_reason(f"отклик настоящего базового прогона Model_Z ({DEFAULT_RESPONSE_PATH})"),
)


@pytest.fixture(scope="module")
def demo_dir(tmp_path_factory: pytest.TempPathFactory) -> Path:
    if not DEFAULT_RESPONSE_PATH.is_file():
        pytest.skip(
            missing_reason(
                f"отклик настоящего базового прогона Model_Z ({DEFAULT_RESPONSE_PATH})"
            )
        )
    out = tmp_path_factory.mktemp("demo")
    build_demo(out)
    return out


def _read(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _nan_safe_equal(left: Any, right: Any) -> bool:
    """`NaN != NaN` в IEEE-754 — `df` per-well законно `NaN` (не определён на
    сумме по горизонту, `economics.npv.py`), сравнивать `==` напрямую нельзя."""

    if isinstance(left, float) and isinstance(right, float) and math.isnan(left) and math.isnan(right):
        return True
    if isinstance(left, dict) and isinstance(right, dict):
        return left.keys() == right.keys() and all(
            _nan_safe_equal(left[key], right[key]) for key in left
        )
    if isinstance(left, list) and isinstance(right, list):
        return len(left) == len(right) and all(
            _nan_safe_equal(a, b) for a, b in zip(left, right)
        )
    return left == right


def test_scale_comes_from_the_deck_not_from_literals(demo_dir: Path) -> None:
    expected_wells = len(load_wellheads(DEFAULT_DECK_PATH))
    timeline = _read(demo_dir / "timeline.json")
    assert len(timeline["wells"]) == expected_wells
    assert len(timeline["steps"]) == N_CONTROL_DATES
    assert timeline["n_intervals"] == N_CONTROL_DATES - 1
    assert len(_read(demo_dir / "npv.json")["wells"]) == expected_wells
    assert len(_read(demo_dir / "wells.json")["wells"]) == expected_wells


@needs_base_run
def test_generation_is_deterministic(tmp_path: Path) -> None:
    first = tmp_path / "a"
    second = tmp_path / "b"
    build_demo(first)
    build_demo(second)
    for path in sorted(first.rglob("*.json")):
        twin = second / path.relative_to(first)
        assert twin.read_text(encoding="utf-8") == path.read_text(encoding="utf-8")


def test_whatif_scenario_carries_the_synthetic_flag(demo_dir: Path) -> None:
    for scenario in (WHATIF_ID,):
        for name in VIEW_FILES:
            data = _read(demo_dir / scenario / name if scenario else demo_dir / name)
            meta = data["__meta__"] if name == "trace.json" else data["meta"]
            assert meta["provenance"] == DEMO_PROVENANCE
            assert meta["synthetic"] is True
            assert meta["notice_ru"] and meta["notice_en"]


def test_base_scenario_is_marked_real_not_synthetic(demo_dir: Path) -> None:
    """G3: `base` — настоящий расчёт, `synthetic-demo` из него убрана (аудит D2)."""

    for scenario in ("", BASE_ID):
        for name in REAL_VIEW_FILES:
            data = _read(demo_dir / scenario / name if scenario else demo_dir / name)
            meta = data["__meta__"] if name == "trace.json" else data["meta"]
            assert meta["provenance"] == REAL_PROVENANCE
            assert meta["synthetic"] is False
            assert meta["notice_ru"] and meta["notice_en"]


def test_scenarios_index_meta_is_honest_about_mixed_provenance(demo_dir: Path) -> None:
    meta = _read(demo_dir / "scenarios.json")["meta"]
    assert meta["provenance"] == "mixed"
    assert meta["synthetic"] is None


def test_wells_json_is_marked_as_real_deck_geometry(demo_dir: Path) -> None:
    meta = _read(demo_dir / "wells.json")["meta"]
    assert meta["provenance"] == "deck"
    assert meta["synthetic"] is False


def test_bundles_validate_against_the_artifact_loader(demo_dir: Path) -> None:
    expected_provenance = {BASE_ID: REAL_PROVENANCE, WHATIF_ID: DEMO_PROVENANCE}
    for name in (BASE_ID, WHATIF_ID):
        artifact = load_bundle(demo_dir / "bundles" / f"{name}.json")
        assert artifact.schedule.meta.provenance == expected_provenance[name]
        assert len(artifact.schedule.meta.wells) == len(deck_scale())
        assert artifact.schedule.meta.n_control_dates == N_CONTROL_DATES


def test_view_files_match_their_builders(demo_dir: Path) -> None:
    artifact = load_bundle(demo_dir / "bundles" / f"{BASE_ID}.json")
    densities = {well: _DEFAULT_DENSITY for well in artifact.schedule.meta.wells}
    exported = _read(demo_dir / "timeline.json")
    assert exported["steps"] == build_timeline(artifact, densities)["steps"]
    assert _read(demo_dir / "graph.json")["nodes"] == build_lambda_graph(artifact)["nodes"]
    assert _nan_safe_equal(
        _read(demo_dir / "npv.json")["wells"], build_npv_by_well(artifact)["wells"]
    )


def test_scenario_index_has_no_submitted_scenario_yet(demo_dir: Path) -> None:
    """`base` — настоящий расчёт, но не прошёл финальный тракт сдачи (задача 62/G6):
    `final_npv` — единственный разрешённый источник заявленного числа (README §6a),
    и заполнять его до тракта — заявлять то, что ещё не проверено."""

    bundles = [demo_dir / "bundles" / f"{name}.json" for name in (BASE_ID, WHATIF_ID)]
    index = build_scenario_index(bundles)
    assert index["submitted"] is None
    assert [entry["id"] for entry in index["scenarios"]] == [BASE_ID, WHATIF_ID]
    for entry in index["scenarios"]:
        assert entry["is_submitted"] is False
        assert entry["npv_methodology"] is None


def test_what_if_scenario_differs_from_the_base(demo_dir: Path) -> None:
    base = _read(demo_dir / "npv.json")
    whatif = _read(demo_dir / WHATIF_ID / "npv.json")
    assert base["npv_methodology"] != whatif["npv_methodology"]


def test_demo_meta_is_honest_about_being_synthetic() -> None:
    meta = demo_meta("timeline")
    assert meta["provenance"] == DEMO_PROVENANCE
    assert meta["synthetic"] is True
    assert "не результат расчёта" in meta["notice_ru"]


def _script_of(artifact: RunArtifact) -> dict:
    densities = {well: _DEFAULT_DENSITY for well in artifact.schedule.meta.wells}
    return build_demo_script(build_timeline(artifact, densities), build_trace(artifact))


def test_demo_script_opens_with_a_morph_frame() -> None:
    frames = _script_of(make_synthetic_artifact())["frames"]
    assert frames[0]["event"] is None
    assert frames[1]["event"] == {"type": "MORPH"}
    assert all(frame["hold_ms"] > 0 for frame in frames)


def test_demo_script_uses_only_the_declared_event_types() -> None:
    frames = _script_of(make_synthetic_artifact())["frames"]
    for frame in frames:
        if frame["event"] is None:
            continue
        assert frame["event"]["type"] in EVENT_TYPES


def test_every_event_frame_is_confirmed_by_the_data_of_its_step() -> None:
    """Кадр без подтверждения интерфейс выбрасывает. Генератор обязан
    выдавать только подтверждаемые: событие берётся из настоящей смены
    состояния или настоящей записи трассы, а не выдумывается."""

    artifact = make_synthetic_artifact()
    densities = {well: _DEFAULT_DENSITY for well in artifact.schedule.meta.wells}
    timeline = build_timeline(artifact, densities)
    trace = build_trace(artifact)
    known = {
        (event["step"], event["type"], event["well"])
        for event in field_events(timeline, trace)
    }
    steps = {step["control_step"]: step for step in timeline["steps"]}
    for frame in build_demo_script(timeline, trace)["frames"]:
        assert frame["step"] in steps
        event = frame["event"]
        if event is None or event["type"] == "MORPH":
            continue
        assert (frame["step"], event["type"], event["well"]) in known
        assert any(row["well"] == event["well"] for row in steps[frame["step"]]["wells"])


def test_rule_fired_frames_name_a_rule_present_in_the_trace() -> None:
    artifact = make_synthetic_artifact()
    trace = build_trace(artifact)
    for frame in _script_of(artifact)["frames"]:
        event = frame["event"]
        if event is None or event["type"] != "RULE_FIRED":
            continue
        records = trace[event["well"]][str(frame["step"])]
        assert event["rule"] in [record["rule"] for record in records]


def test_demo_script_is_deterministic() -> None:
    artifact = make_synthetic_artifact()
    assert _script_of(artifact) == _script_of(artifact)


def test_demo_script_fits_the_target_length() -> None:
    """~60 секунд: ролик показывают на защите, и он не должен ни обрываться,
    ни идти вдвое дольше слота."""

    script = _script_of(make_synthetic_artifact())
    assert script["total_ms"] == sum(frame["hold_ms"] for frame in script["frames"])
    assert script["total_ms"] <= TARGET_TOTAL_MS


def test_demo_script_of_the_real_scale_bundle_uses_the_whole_slot() -> None:
    whatif = build_demo_artifact(
        wells=deck_scale(),
        n_control_dates=N_CONTROL_DATES,
        n_deck_dates=N_DECK_DATES,
        t0=T0,
        seed=DEMO_SEED + 1,
        tag=WHATIF_ID,
    )
    script = _script_of(whatif)
    assert script["total_ms"] > TARGET_TOTAL_MS * 0.8
    assert script["total_ms"] <= TARGET_TOTAL_MS
    types = {
        frame["event"]["type"] for frame in script["frames"] if frame["event"]
    }
    assert "MORPH" in types
    assert types - {"MORPH"}
    assert types <= set(EVENT_TYPES)


def _with_events(artifact: RunArtifact, *events: ControlEvent) -> RunArtifact:
    schedule = replace(
        artifact.schedule,
        control_events=tuple(artifact.schedule.control_events) + events,
    )
    return replace(artifact, schedule=schedule)


def test_state_transitions_of_the_bundle_become_events() -> None:
    """Смена роли и остановка обязаны попадать в список кадров: без них
    ролик показывает одни правила и о жизни фонда не рассказывает."""

    artifact = _with_events(
        make_synthetic_artifact(),
        ControlEvent(control_step=2, well="11", kind=EventKind.SHUT),
        ControlEvent(control_step=4, well="13", kind=EventKind.CONVERT_INJ),
    )
    densities = {well: _DEFAULT_DENSITY for well in artifact.schedule.meta.wells}
    events = field_events(build_timeline(artifact, densities), build_trace(artifact))
    assert {"step": 2, "type": "SHUT", "well": "11"} in events
    assert {"step": 4, "type": "ROLE_CHANGE", "well": "13"} in events


def test_commissioning_of_a_late_well_becomes_an_event() -> None:
    artifact = make_synthetic_artifact()
    late = artifact.schedule.meta.wells[-1]
    schedule = replace(
        artifact.schedule,
        fixed_deck_events=tuple(artifact.schedule.fixed_deck_events)
        + (
            FixedDeckEvent(
                control_step=3,
                well=late,
                operator="COMPDAT",
                raw_args=("10", "10", "1", "2", "OPEN"),
            ),
        ),
    )
    artifact = replace(artifact, schedule=schedule)
    densities = {well: _DEFAULT_DENSITY for well in artifact.schedule.meta.wells}
    events = field_events(build_timeline(artifact, densities), build_trace(artifact))
    assert {"step": 3, "type": "COMMISSIONED", "well": late} in events
    types = {
        frame["event"]["type"]
        for frame in _script_of(artifact)["frames"]
        if frame["event"]
    }
    assert "COMMISSIONED" in types


def test_export_demo_script_writes_compact_json(tmp_path: Path) -> None:
    artifact = make_synthetic_artifact()
    densities = {well: _DEFAULT_DENSITY for well in artifact.schedule.meta.wells}
    out = export_demo_script_json(
        build_timeline(artifact, densities),
        build_trace(artifact),
        tmp_path / "demo-script.json",
    )
    text = out.read_text(encoding="utf-8")
    assert ", " not in text
    assert json.loads(text) == _script_of(artifact)


@needs_base_run
def test_new_view_files_are_written_for_every_scenario(demo_dir: Path) -> None:
    for scenario in ("", BASE_ID, WHATIF_ID):
        root = demo_dir / scenario if scenario else demo_dir
        for name in ("hierarchy.json", "ablation.json"):
            data = _read(root / name)
            assert data["meta"]["kind"] in ("hierarchy", "ablation")
            assert data["meta"]["synthetic"] is True


@needs_base_run
def test_root_scoped_files_are_written_once(demo_dir: Path) -> None:
    for name in ROOT_FILES:
        assert (demo_dir / name).is_file()
    assert not (demo_dir / BASE_ID / "demo-script.json").exists()
    assert not (demo_dir / WHATIF_ID / "demo-script.json").exists()


@needs_base_run
def test_scenarios_index_shows_both_measured_and_not_measured(demo_dir: Path) -> None:
    by_id = {entry["id"]: entry for entry in _read(demo_dir / "scenarios.json")["scenarios"]}
    base = by_id[BASE_ID]
    assert base["ood_score"] is not None
    assert base["ood_threshold"] is not None
    assert base["worst_regret"]["part"] in ("holdout", "optimization")
    assert base["final_npv"] is None
    whatif = by_id[WHATIF_ID]
    assert whatif["ood_score"] is None
    assert whatif["worst_regret"] is None
    assert whatif["final_npv"] is None


@needs_base_run
def test_timeline_carries_the_compensation_corridor(demo_dir: Path) -> None:
    corridor = _read(demo_dir / "timeline.json")["field_norms"]["compensation"]
    assert corridor["min"] < corridor["max"]
