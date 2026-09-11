from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from backend.contexts.policy.domain.policy import Rule

from backend.contexts.showcase.application.exporters.ablation_view import (
    ABLATION_NOT_RUN,
    ABLATION_PROVENANCE,
    DISABLED_RULES,
    UPLIFT_NOT_MEASURED,
    build_ablation,
    export_ablation_json,
)
from tests.support.backend.showcase_fixtures import make_synthetic_artifact

pytestmark = [pytest.mark.slow, pytest.mark.showcase]

SEED = 20260815


def _by_rule(document: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {row["rule"]: row for row in document["rules"]}


def test_every_rule_of_the_contract_is_present_once() -> None:
    rows = build_ablation(make_synthetic_artifact(), SEED)["rules"]
    names = [row["rule"] for row in rows]
    assert names == sorted(rule.value for rule in Rule)
    assert len(names) == len(set(names))


def test_npv_total_comes_from_the_artifact() -> None:
    artifact = make_synthetic_artifact()
    document = build_ablation(artifact, SEED)
    assert document["npv_total"] == pytest.approx(artifact.npv_table.npv_methodology)


def test_no_rule_carries_a_money_contribution() -> None:
    for row in build_ablation(make_synthetic_artifact(), SEED)["rules"]:
        assert row["delta_npv"] is None
        assert row["share"] is None


def test_absent_contribution_is_never_reported_as_zero() -> None:
    for row in build_ablation(make_synthetic_artifact(), SEED)["rules"]:
        assert row["delta_npv"] != 0
        assert row["share"] != 0


def test_every_rule_explains_why_the_contribution_is_missing() -> None:
    for row in build_ablation(make_synthetic_artifact(), SEED)["rules"]:
        assert row["delta_npv_status"] == ABLATION_NOT_RUN


def test_document_states_that_uplift_was_not_measured() -> None:
    document = build_ablation(make_synthetic_artifact(), SEED)
    assert document["uplift_measured"] is False
    assert document["uplift_reason"] == ABLATION_NOT_RUN


def test_document_is_not_marked_synthetic_because_nothing_is_invented() -> None:
    meta = build_ablation(make_synthetic_artifact(), SEED)["meta"]
    assert meta["synthetic"] is False
    assert meta["provenance"] == ABLATION_PROVENANCE
    assert meta["uplift_measured"] is False
    assert meta["uplift_reason"] == ABLATION_NOT_RUN


def test_enabled_flag_still_reports_whether_the_rule_was_on() -> None:
    by_rule = _by_rule(build_ablation(make_synthetic_artifact(), SEED))
    for name, row in by_rule.items():
        assert row["enabled"] is (name not in DISABLED_RULES)


def test_disabled_rule_carries_a_reason() -> None:
    by_rule = _by_rule(build_ablation(make_synthetic_artifact(), SEED))
    assert "R7" in DISABLED_RULES
    row = by_rule["R7"]
    assert row["enabled"] is False
    assert row["disabled_reason"] == UPLIFT_NOT_MEASURED


def test_enabled_rules_do_not_carry_a_disabled_reason() -> None:
    for row in build_ablation(make_synthetic_artifact(), SEED)["rules"]:
        if row["enabled"]:
            assert "disabled_reason" not in row
        else:
            assert row["disabled_reason"]


def test_generation_does_not_depend_on_the_seed() -> None:
    artifact = make_synthetic_artifact()
    assert build_ablation(artifact, SEED) == build_ablation(artifact, SEED + 1)


def test_export_writes_compact_json(tmp_path: Path) -> None:
    artifact = make_synthetic_artifact()
    out = export_ablation_json(artifact, tmp_path / "ablation.json", SEED)
    text = out.read_text(encoding="utf-8")
    assert '", "' not in text
    assert '": ' not in text
    assert json.loads(text) == build_ablation(artifact, SEED)


def test_null_survives_the_serialisation_as_null_not_as_zero(tmp_path: Path) -> None:
    out = export_ablation_json(
        make_synthetic_artifact(), tmp_path / "ablation.json", SEED
    )
    text = out.read_text(encoding="utf-8")
    assert '"delta_npv":null' in text
    assert '"delta_npv":0' not in text
    assert '"share":0' not in text
    for row in _by_rule(json.loads(text)).values():
        assert row["delta_npv"] is None
        assert row["share"] is None
