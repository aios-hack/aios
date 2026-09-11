from __future__ import annotations

import ast
from dataclasses import fields
from pathlib import Path

import pytest

from backend.contexts.constraints.domain.config import ArtifactHashes, Budgets, NormativeSet
from backend.contexts.constraints.domain.config import DEFAULT_NORMATIVES_2007

from backend.contexts.constraints.domain.schema import COMPONENT_SEEDS, GLOBAL_SEED_KEY
from backend.contexts.constraints.domain.schema import DEFAULT_BUDGETS, default_seeds
from tests.support.backend.paths import REPO_ROOT

OWNED_PACKAGES: tuple[str, ...] = (
    "backend/contexts/connectivity/domain",
    "backend/contexts/policy/domain",
    "backend/contexts/robustness/domain",
    "backend/contexts/constraints/domain/normatives.py",
    "backend/contexts/constraints/domain/schema.py",
    "backend/contexts/constraints/infrastructure",
)
ROOT = REPO_ROOT

NORMATIVE_VALUES: frozenset[float] = frozenset(
    {
        28_000.0,
        19_600.0,
        40.0,
        100.0,
        30.0,
        1_000_000.0,
        1_800_000.0,
        5_000_000.0,
        0.10,
        0.022,
        0.25,
    }
)

TECHNICAL_TOLERANCE_LITERALS: dict[str, frozenset[str]] = {
    "backend/contexts/constraints/domain/schema.py": frozenset(
        {"injection_shortfall_tolerance", "separation_floor_share"}
    ),
    "backend/contexts/connectivity/domain/groups.py": frozenset({"DEFAULT_QUANTILE_GRID"}),
    "backend/contexts/policy/domain/agents/pressure.py": frozenset({"APPROACH_FRACTION"}),
}

PERCENT_SCALE_VALUES: frozenset[float] = frozenset({100.0})

DECK_SCALE_VALUES: frozenset[float] = frozenset(
    {146.0, 147.0, 225.0, 224.0, 103.0, 371.0, 27.0, 41.0}
)

ALLOWED_IN_TESTS = "tests"


def owned_sources() -> list[Path]:
    sources: list[Path] = []
    for package in OWNED_PACKAGES:
        target = ROOT / package
        if target.is_file():
            sources.append(target)
            continue
        if not target.is_dir():
            continue
        for path in target.rglob("*.py"):
            if ALLOWED_IN_TESTS in path.parts:
                continue
            sources.append(path)
    return sources


def numeric_literals(path: Path) -> list[tuple[int, float]]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    found: list[tuple[int, float]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
            if isinstance(node.value, bool):
                continue
            found.append((node.lineno, float(node.value)))
    return found


def allowed_technical_tolerance_lines(path: Path) -> set[int]:

    names = TECHNICAL_TOLERANCE_LITERALS.get(path.relative_to(ROOT).as_posix())
    if names is None:
        return set()
    tree = ast.parse(path.read_text(encoding="utf-8"))
    lines: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and isinstance(node.value, ast.Tuple):
            assigned = {
                target.id for target in node.targets if isinstance(target, ast.Name)
            }
            if assigned & names:
                for element in node.value.elts:
                    if isinstance(element, ast.Constant) and isinstance(
                        element.value, (int, float)
                    ):
                        lines.add(element.lineno)
            continue
        if isinstance(node, ast.AnnAssign) and isinstance(node.value, ast.Tuple):
            if isinstance(node.target, ast.Name) and node.target.id in names:
                for element in node.value.elts:
                    if isinstance(element, ast.Constant) and isinstance(
                        element.value, (int, float)
                    ):
                        lines.add(element.lineno)
            continue
        if isinstance(node, ast.AnnAssign) and isinstance(node.value, ast.Constant):
            if isinstance(node.target, ast.Name) and node.target.id in names:
                value = node.value
                if isinstance(value.value, (int, float)) and not isinstance(
                    value.value, bool
                ):
                    lines.add(value.lineno)
            continue
        if isinstance(node, ast.Assign) and isinstance(node.value, ast.Constant):
            value = node.value
            if not isinstance(value.value, (int, float)) or isinstance(value.value, bool):
                continue
            if float(value.value) != 0.10:
                continue
            assigned = {
                target.id for target in node.targets if isinstance(target, ast.Name)
            }
            if assigned & names:
                lines.add(value.lineno)
        elif isinstance(node, ast.keyword) and isinstance(node.value, ast.Constant):
            value = node.value
            if not isinstance(value.value, (int, float)) or isinstance(value.value, bool):
                continue
            if float(value.value) != 0.10:
                continue
            if node.arg in names:
                lines.add(value.lineno)
    return lines


def test_owned_packages_are_scanned() -> None:
    sources = owned_sources()
    assert sources
    covered = {path.as_posix() for path in sources}
    assert any("/contexts/connectivity/" in name for name in covered)
    assert any("/contexts/constraints/" in name for name in covered)
    assert any("/contexts/policy/" in name for name in covered)
    assert any("/contexts/robustness/" in name for name in covered)


def test_no_normative_value_is_hardcoded_outside_the_config() -> None:
    offenders: list[str] = []
    for path in owned_sources():
        allowed_lines = allowed_technical_tolerance_lines(path)
        for line, value in numeric_literals(path):
            if value == 0.10 and line in allowed_lines:
                continue
            if value in NORMATIVE_VALUES:
                offenders.append(f"{path.relative_to(ROOT)}:{line} → {value}")
    assert offenders == [], (
        "normatives are read bypassing the config: " + "; ".join(offenders)
    )


def test_wacc_normative_is_explicitly_protected() -> None:
    assert DEFAULT_NORMATIVES_2007["wacc"] == pytest.approx(0.10)


def test_no_deck_scale_literal_is_hardcoded() -> None:
    offenders: list[str] = []
    for path in owned_sources():
        for line, value in numeric_literals(path):
            if value in DECK_SCALE_VALUES:
                offenders.append(f"{path.relative_to(ROOT)}:{line} → {value}")
    assert offenders == [], (
        "scale and well stock literals are derived from data, not written as numbers: "
        + "; ".join(offenders)
    )


def test_every_normative_field_is_reachable_from_the_config() -> None:
    from tests.backend.contexts.constraints.conftest import a_hash

    from backend.contexts.constraints.domain.schema import default_config
    from backend.contexts.constraints.domain.config import DEFAULT_NORMATIVES_2007

    config = default_config(
        normatives=NormativeSet(esp_catalog=(), **DEFAULT_NORMATIVES_2007),
        hashes=ArtifactHashes(
            deck_hash=a_hash("a"),
            history_prefix_hash=a_hash("b"),
            summary_spec_hash=a_hash("c"),
            groups_hash=a_hash("d"),
            dataset_version_hash=a_hash("e"),
            surrogate_checkpoint_hash=a_hash("f"),
        ),
        global_seed=1,
    )
    for field in fields(NormativeSet):
        assert hasattr(config.normatives, field.name)
    for field in fields(Budgets):
        assert hasattr(config.budgets, field.name)


def test_default_seeds_cover_every_declared_component() -> None:
    seeds = default_seeds(7)
    assert seeds[GLOBAL_SEED_KEY] == 7
    for component in COMPONENT_SEEDS:
        assert component in seeds
    assert len(set(seeds.values())) == len(seeds)


def test_default_budgets_are_positive() -> None:
    assert DEFAULT_BUDGETS.runs_per_verification_round > 0
    assert DEFAULT_BUDGETS.fixed_point_iteration_cap > 0
