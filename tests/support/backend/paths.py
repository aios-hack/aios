from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
TESTS_ROOT = REPO_ROOT / "tests"
FIXTURES_ROOT = TESTS_ROOT / "fixtures"
DECKS_ROOT = FIXTURES_ROOT / "decks"
CONFIG_ROOT = REPO_ROOT / "config"
DATA_ROOT = REPO_ROOT / "data"
OUT_ROOT = REPO_ROOT / "out"
GOLDEN_ROOT = TESTS_ROOT / "golden"
FRONTEND_PUBLIC = REPO_ROOT / "frontend" / "public"


def repo_path(*parts: str) -> Path:
    return REPO_ROOT.joinpath(*parts)


def fixture_path(*parts: str) -> Path:
    return FIXTURES_ROOT.joinpath(*parts)


def deck_path(name: str) -> Path:
    return DECKS_ROOT / name


def config_path(*parts: str) -> Path:
    return CONFIG_ROOT.joinpath(*parts)


__all__ = [
    "CONFIG_ROOT",
    "DATA_ROOT",
    "DECKS_ROOT",
    "FIXTURES_ROOT",
    "FRONTEND_PUBLIC",
    "GOLDEN_ROOT",
    "OUT_ROOT",
    "REPO_ROOT",
    "TESTS_ROOT",
    "config_path",
    "deck_path",
    "fixture_path",
    "repo_path",
]
