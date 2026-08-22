from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from backend.core.contracts import OperatingStatus, Role

from backend.domain.connectivity import DeckSchedule, parse_deck_schedule

from backend.domain.connectivity.tests.conftest import deck_path


def test_wells_axis_is_lexicographic_and_complete(deck: DeckSchedule) -> None:
    assert list(deck.wells) == sorted(deck.wells)
    assert len(deck.wells) == len(set(deck.wells))
    assert len(deck.wells) == 103


def test_every_record_refers_to_declared_well(deck: DeckSchedule) -> None:
    assert {r.well for r in deck.records} == set(deck.wells)


def test_roles_come_from_both_keywords(deck: DeckSchedule) -> None:
    roles = {r.role for r in deck.records}
    assert roles == {Role.PROD, Role.INJ}


def test_setpoints_are_non_negative(deck: DeckSchedule) -> None:
    assert all(r.setpoint_m3_per_day >= 0.0 for r in deck.records)


def test_shut_records_exist_only_on_producing_side(deck: DeckSchedule) -> None:
    shut = [r for r in deck.records if r.operating_status is OperatingStatus.SHUT]
    assert shut
    assert {r.role for r in shut} == {Role.PROD}


def test_date_index_is_monotone_lookup(deck: DeckSchedule) -> None:
    assert deck.date_index(deck.dates[0]) == 0
    assert deck.date_index(deck.dates[-1]) == len(deck.dates) - 1
    assert deck.date_index(date(2007, 1, 1)) == 146


def test_records_at_returns_only_that_date(deck: DeckSchedule) -> None:
    index = deck.date_index(date(2007, 1, 1))
    at = deck.records_at(index)
    assert at
    assert all(r.deck_date_index == index for r in at)


def test_comment_rows_do_not_become_records(deck: DeckSchedule) -> None:
    text = deck_path().read_text(encoding="utf-8", errors="replace")
    assert "-- WELL I J K1 K2" in text
    assert all(not r.well.startswith("-") for r in deck.records)


def test_deck_without_dates_is_rejected(tmp_path: Path) -> None:
    broken = tmp_path / "no_dates.inc"
    broken.write_text("WELSPECS\n '1' 'GROUP' 1 1 1* 'OIL' /\n/\n", encoding="utf-8")
    with pytest.raises(ValueError, match="нет ни одной DATES"):
        parse_deck_schedule(broken)


def test_records_before_first_dates_are_rejected(tmp_path: Path) -> None:
    broken = tmp_path / "early_wcon.inc"
    broken.write_text(
        "WELSPECS\n '1' 'GROUP' 1 1 1* 'OIL' /\n/\n\n"
        "WCONPROD\n '1' 'OPEN' 'LRAT' 1* 1* 1* 20.0 1* 50 1* 1* /\n/\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="до первой DATES"):
        parse_deck_schedule(broken)


def test_unknown_well_is_rejected(tmp_path: Path) -> None:
    broken = tmp_path / "unknown_well.inc"
    broken.write_text(
        "WELSPECS\n '1' 'GROUP' 1 1 1* 'OIL' /\n/\n\n"
        "DATES\n 01 JAN 2007 /\n/\n\n"
        "WCONPROD\n '9' 'OPEN' 'LRAT' 1* 1* 1* 20.0 1* 50 1* 1* /\n/\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="вне WELSPECS"):
        parse_deck_schedule(broken)
