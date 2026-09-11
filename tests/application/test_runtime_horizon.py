import json
import os
import subprocess
import sys

import pytest

from backend.contexts.reservoir.domain.horizon import load_horizon


def test_changed_horizon_reaches_contracts_economics_and_response_offsets(tmp_path):
    path = tmp_path / "horizon.json"
    path.write_text(json.dumps(dict(t0="2017-01-01", n_intervals=12,
                                   n_deck_dates=33, discount_base_year=2017)))
    program = """
from backend.contexts.schedule.domain.schedule import T0, N_INTERVALS
from backend.contexts.reservoir.domain.response import N_DECK_DATES
from backend.contexts.reservoir.domain.horizon import HORIZON
from backend.contexts.economics.domain.npv import DISCOUNT_BASE_YEAR
from backend.contexts.simulation.infrastructure.response_loader import _control_step_for_date
assert str(T0) == '2017-01-01'
assert N_INTERVALS == 12 and N_DECK_DATES == 33
assert DISCOUNT_BASE_YEAR == 2017
assert HORIZON.history_offset == 20
assert _control_step_for_date(19) is None
assert _control_step_for_date(20) == -1
assert _control_step_for_date(21) == 0
assert _control_step_for_date(32) == 11
"""
    subprocess.run([sys.executable, "-c", program], check=True,
                   env={**os.environ, "AIOS_HORIZON_PATH": str(path)})


@pytest.mark.parametrize("changes", [{"n_intervals": True}, {"n_intervals": 0},
                                    {"n_deck_dates": 1}, {"t0": "2017-01-15"}])
def test_invalid_horizon_fails_before_simulation(tmp_path, changes):
    data = dict(t0="2017-01-01", n_intervals=12, n_deck_dates=20, discount_base_year=2017)
    path = tmp_path / "horizon.json"
    path.write_text(json.dumps({**data, **changes}))
    with pytest.raises(ValueError):
        load_horizon(str(path))
