from __future__ import annotations

import json
from pathlib import Path

import pytest

from backend.application.cases import (
    REFUSED_SECTIONS,
    TOP_LEVEL_SECTIONS,
    YEAR_SECTIONS,
    CaseError,
    constraints_from_json,
    load_case,
)
from backend.core.contracts import Constraints
from backend.domain.configuration.constraints_io import (
    constraints_from_json as io_constraints_from_json,
    constraints_hash,
    constraints_to_json,
)


def write_case(path: Path, document: dict[str, object]) -> Path:
    path.write_text(
        json.dumps(document, ensure_ascii=False), encoding="utf-8"
    )
    return path


def test_oil_limits_is_no_longer_refused() -> None:
    assert "oil_limits" not in REFUSED_SECTIONS
    assert "oil_limits" in YEAR_SECTIONS
    assert "oil_limits" in TOP_LEVEL_SECTIONS


def test_case_with_oil_limits_is_accepted(tmp_path: Path) -> None:
    case = write_case(
        tmp_path / "case.json",
        {"oil_limits": {"2010": 2600.0, "2011": 2400.0}},
    )

    constraints = load_case(case)

    assert constraints.oil_limits == {2010: 2600.0, 2011: 2400.0}
    assert constraints.case_path == str(case)


def test_year_may_be_a_number_or_a_string() -> None:
    constraints = constraints_from_json({"oil_limits": {2010: 2600.0}})

    assert constraints.oil_limits == {2010: 2600.0}


def test_negative_oil_limit_is_refused() -> None:
    with pytest.raises(CaseError, match="oil_limits"):
        constraints_from_json({"oil_limits": {"2010": -1.0}})


def test_non_numeric_oil_limit_is_refused() -> None:
    with pytest.raises(CaseError, match="oil_limits"):
        constraints_from_json({"oil_limits": {"2010": "много"}})


def test_nan_oil_limit_is_refused() -> None:
    with pytest.raises(CaseError, match="oil_limits"):
        constraints_from_json({"oil_limits": {"2010": float("nan")}})


def test_missing_section_defaults_to_empty() -> None:
    assert constraints_from_json({}).oil_limits == {}


def test_oil_limits_survives_the_json_round_trip() -> None:
    constraints = Constraints(oil_limits={2010: 2600.0, 2011: 2400.0})

    document = constraints_to_json(constraints)
    restored = io_constraints_from_json(document)

    assert document["oil_limits"] == {"2010": 2600.0, "2011": 2400.0}
    assert restored.oil_limits == constraints.oil_limits


def test_oil_limits_changes_the_constraints_hash() -> None:
    empty = Constraints()
    declared = Constraints(oil_limits={2010: 2600.0})
    changed = Constraints(oil_limits={2010: 2600.5})

    assert constraints_hash(declared) != constraints_hash(empty)
    assert constraints_hash(changed) != constraints_hash(declared)
    assert constraints_hash(declared) == constraints_hash(
        Constraints(oil_limits={2010: 2600.0})
    )


def test_shipped_cases_declare_the_section() -> None:
    for name in ("config/competition-constraints.json", "config/cases/base.json"):
        constraints = load_case(Path(name))
        assert constraints.oil_limits == {}
        assert "oil_limits" in json.loads(
            Path(name).read_text(encoding="utf-8")
        )
