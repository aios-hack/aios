from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from aios_backend.core.contracts import Rule

from aios_backend.presentation.ui_export.ablation_view import (
    DISABLED_RULES,
    MEASURED_RULES,
    UNMEASURED_RULES,
    UPLIFT_NOT_MEASURED,
    ZERO_RULES,
    build_ablation,
    export_ablation_json,
)
from aios_backend.presentation.ui_export.fixtures import make_synthetic_artifact

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
    assert document["npv_total"] == pytest.approx(
        artifact.npv_table.npv_methodology
    )


def test_measured_zero_and_not_measured_are_different_things() -> None:
    """`0.0` — измеренный ноль, `null` — не измерено. Оба случая обязаны быть
    в наборе: иначе интерфейс рендерит только ту ветку, которая случайно
    попалась."""

    by_rule = _by_rule(build_ablation(make_synthetic_artifact(), SEED))
    zero = by_rule[ZERO_RULES[0]]
    assert zero["delta_npv"] == 0.0
    assert zero["delta_npv"] is not None
    assert zero["share"] == 0.0
    assert zero["enabled"] is True
    for name in UNMEASURED_RULES:
        unmeasured = by_rule[name]
        assert unmeasured["delta_npv"] is None
        assert unmeasured["share"] is None
        assert unmeasured["enabled"] is True


def test_disabled_rule_carries_a_reason() -> None:
    by_rule = _by_rule(build_ablation(make_synthetic_artifact(), SEED))
    assert "R7" in DISABLED_RULES
    row = by_rule["R7"]
    assert row["enabled"] is False
    assert row["delta_npv"] is None
    assert row["share"] is None
    assert row["disabled_reason"] == UPLIFT_NOT_MEASURED


def test_enabled_rules_do_not_carry_a_disabled_reason() -> None:
    for row in build_ablation(make_synthetic_artifact(), SEED)["rules"]:
        if row["enabled"]:
            assert "disabled_reason" not in row
        else:
            assert row["disabled_reason"]


def test_measured_rules_agree_with_their_share_of_the_total() -> None:
    document = build_ablation(make_synthetic_artifact(), SEED)
    by_rule = _by_rule(document)
    total = document["npv_total"]
    for name in MEASURED_RULES:
        row = by_rule[name]
        assert row["delta_npv"] is not None
        assert row["share"] is not None
        assert row["delta_npv"] == pytest.approx(total * row["share"], rel=1e-6)


def test_measured_shares_do_not_claim_the_whole_npv() -> None:
    document = build_ablation(make_synthetic_artifact(), SEED)
    measured = [row["share"] for row in document["rules"] if row["share"] is not None]
    assert measured
    assert 0.0 <= sum(measured) < 1.0


def test_classification_covers_every_rule_without_overlap() -> None:
    groups = (
        set(MEASURED_RULES),
        set(ZERO_RULES),
        set(UNMEASURED_RULES),
        set(DISABLED_RULES),
    )
    union: set[str] = set()
    for group in groups:
        assert not union & group
        union |= group
    assert union == {rule.value for rule in Rule}


def test_generation_is_deterministic_for_one_seed() -> None:
    artifact = make_synthetic_artifact()
    assert build_ablation(artifact, SEED) == build_ablation(artifact, SEED)
    assert build_ablation(artifact, SEED) != build_ablation(artifact, SEED + 1)


def test_export_writes_compact_json(tmp_path: Path) -> None:
    artifact = make_synthetic_artifact()
    out = export_ablation_json(artifact, tmp_path / "ablation.json", SEED)
    text = out.read_text(encoding="utf-8")
    assert ", " not in text
    assert '": ' not in text
    assert json.loads(text) == build_ablation(artifact, SEED)


def test_null_survives_the_serialisation_as_null_not_as_zero(tmp_path: Path) -> None:
    out = export_ablation_json(
        make_synthetic_artifact(), tmp_path / "ablation.json", SEED
    )
    text = out.read_text(encoding="utf-8")
    assert '"delta_npv":null' in text
    assert '"delta_npv":0.0' in text
    restored = _by_rule(json.loads(text))
    assert restored[UNMEASURED_RULES[0]]["delta_npv"] is None
    assert restored[ZERO_RULES[0]]["delta_npv"] == 0.0
