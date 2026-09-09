from types import SimpleNamespace

import pytest

from backend.application.cases import load_case
from backend.application.optimization.observed_repair import repair_from_observation
from backend.core.contracts import EventKind
from backend.core.horizon import HORIZON
from backend.domain.schedule import parse_schedule
from tests.application.test_run_workflow import historical_schedule, historical_model_dir


def test_observed_water_caps_targets_and_bad_pressure_reduces_only_the_affected_control(tmp_path):
    from pathlib import Path
    schedule = historical_schedule()
    model = historical_model_dir(tmp_path / "model")
    parsed = parse_schedule((model / "Model_Z_sch.inc").read_bytes())
    dates = parsed.dates[parsed.t0_deck_date_index:]
    response = SimpleNamespace(
        interval_response=[SimpleNamespace(control_step=0, liquid_volume_delta=1550.0, oil_mass_delta=0.0)],
        state_at_date=[SimpleNamespace(deck_date_index=HORIZON.history_offset + 1,
                                      well="W1", liquid_rate=100.0, injection_rate=0.0, bhp=45.0)],
    )
    repaired = repair_from_observation(schedule, response, dates,
                                       load_case(Path("config/competition-constraints.json")), water_margin=0.8)
    injection = [e for e in repaired.control_events if e.kind is EventKind.SET_RATE and e.control_step == 0]
    assert sum(e.value for e in injection) == pytest.approx(40.0)
    production = [e for e in repaired.control_events if e.kind is EventKind.SET_LRAT and e.control_step == 0]
    assert production[0].value == pytest.approx(80.0)
    assert repaired.initial_state == schedule.initial_state
    assert repaired.fixed_deck_events == schedule.fixed_deck_events
