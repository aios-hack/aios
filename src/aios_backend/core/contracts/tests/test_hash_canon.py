"""G2: contracts и schedule дают один хеш и один порядок оси скважин."""

from __future__ import annotations

import pytest

from aios_backend.infrastructure.opm import OpmDeckEmitter
from aios_backend.core.contracts import Rule, canonical_bytes, hash_schedule
from aios_backend.domain.schedule import build_schedule, deck_well_axis, hash_canonical_schedule, parse_schedule

import conftest

MODEL_Z = conftest.model_z_dir()

pytestmark = pytest.mark.skipif(
    MODEL_Z is None, reason=conftest.missing_reason("Model_Z")
)


def _real_schedule():
    emitter = OpmDeckEmitter(MODEL_Z)
    raw = (MODEL_Z / "Model_Z_sch.inc").read_bytes()
    parsed = parse_schedule(raw)
    return emitter, build_schedule(parsed, raw)


def test_contracts_hash_matches_strict_schedule_hash_on_base_schedule() -> None:
    _, schedule = _real_schedule()
    assert hash_schedule(schedule) == hash_canonical_schedule(schedule)


def test_canonical_bytes_does_not_fail_on_enum_dict_keys() -> None:
    rules = {rule: rule is Rule.R0 for rule in Rule}
    raw = canonical_bytes(rules)
    assert b'"R0":true' in raw


def test_well_axis_matches_across_contracts_schedule_and_bridge() -> None:
    emitter, schedule = _real_schedule()
    raw = (MODEL_Z / "Model_Z_sch.inc").read_bytes()
    assert deck_well_axis(raw) == emitter.source_wells == schedule.meta.wells
