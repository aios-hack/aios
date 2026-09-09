from datetime import date
from types import SimpleNamespace

import pytest

from backend.domain.economics import reference_parity as parity


def test_reference_receives_exact_aios_start_not_beginning_of_year(monkeypatch):
    monkeypatch.setattr(parity, "load_reference_module", lambda _: SimpleNamespace(
        REQUIRED_COLUMNS=(), compute_calculation=lambda *args, **kwargs: kwargs))
    monkeypatch.setattr(parity, "reference_assumptions", lambda *args: {})
    monkeypatch.setattr(parity, "reference_pumps", lambda *args: [])
    assert parity.run_reference("unused", [], None, None, start_date=date(2017, 7, 1))["start_date"] == "2017-07-01"
    assert parity.run_reference("unused", [], None, None, start_year=2017)["start_date"] == "2017-01-01"
    with pytest.raises(ValueError, match="not both"):
        parity.run_reference("unused", [], None, None, start_year=2017, start_date=date(2017, 7, 1))
