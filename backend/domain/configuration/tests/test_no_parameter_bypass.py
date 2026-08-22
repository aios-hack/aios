from __future__ import annotations

import ast
from dataclasses import fields
from pathlib import Path

import pytest

from backend.core.contracts import ArtifactHashes, Budgets, NormativeSet

from backend.domain.configuration import COMPONENT_SEEDS, GLOBAL_SEED_KEY
from backend.domain.configuration.schema import DEFAULT_BUDGETS, default_seeds

OWNED_PACKAGES: tuple[str, ...] = (
    "domain/connectivity",
    "domain/policy",
    "domain/robustness",
    "domain/configuration",
)
ROOT = Path(__file__).resolve().parents[3]

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
        0.022,
        0.25,
    }
)

# ``0.10`` нельзя проверять простым поиском числа: это одновременно ставка
# дисконтирования из методики и нормальный технический допуск/доля в измерении
# связности. Экономический норматив проверяется parity-тестами, а этот тест
# остаётся защитой от прочих уникальных нормативных значений.

DECK_SCALE_VALUES: frozenset[float] = frozenset(
    {146.0, 147.0, 225.0, 224.0, 103.0, 371.0, 27.0, 41.0}
)

ALLOWED_IN_TESTS = "tests"


def owned_sources() -> list[Path]:
    sources: list[Path] = []
    for package in OWNED_PACKAGES:
        directory = ROOT / package
        if not directory.exists():
            continue
        for path in directory.rglob("*.py"):
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


def test_owned_packages_are_scanned() -> None:
    sources = owned_sources()
    assert sources
    assert any(path.parts[-2] == "connectivity" for path in sources)
    assert any(path.parts[-2] == "configuration" for path in sources)


def test_no_normative_value_is_hardcoded_outside_the_config() -> None:
    offenders: list[str] = []
    for path in owned_sources():
        for line, value in numeric_literals(path):
            if value in NORMATIVE_VALUES:
                offenders.append(f"{path.relative_to(ROOT)}:{line} → {value}")
    assert offenders == [], (
        "нормативы читаются мимо конфига: " + "; ".join(offenders)
    )


def test_no_deck_scale_literal_is_hardcoded() -> None:
    offenders: list[str] = []
    for path in owned_sources():
        for line, value in numeric_literals(path):
            if value in DECK_SCALE_VALUES:
                offenders.append(f"{path.relative_to(ROOT)}:{line} → {value}")
    assert offenders == [], (
        "литералы шкал и фонда выводятся из данных, а не пишутся числом: "
        + "; ".join(offenders)
    )


def test_every_normative_field_is_reachable_from_the_config() -> None:
    from backend.domain.configuration.tests.conftest import a_hash

    from backend.domain.configuration import default_config
    from backend.core.contracts import DEFAULT_NORMATIVES_2007

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
