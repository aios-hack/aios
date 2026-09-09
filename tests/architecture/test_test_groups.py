from __future__ import annotations

import tomllib
from pathlib import Path

import conftest
from backend.core.paths import project_root

REQUIRED_MARKERS: tuple[str, ...] = ("slow", "opm", "showcase")


def pytest_config() -> dict[str, object]:
    text = (project_root() / "pyproject.toml").read_text(encoding="utf-8")
    return tomllib.loads(text)["tool"]["pytest"]["ini_options"]


def test_default_run_excludes_the_slow_group() -> None:
    options = pytest_config()
    addopts = options.get("addopts", "")
    assert "not slow" in str(addopts), addopts


def test_every_used_marker_is_declared() -> None:
    options = pytest_config()
    declared = {str(entry).split(":", 1)[0].strip() for entry in options.get("markers", [])}
    assert set(REQUIRED_MARKERS) <= declared, declared
    used: set[str] = set()
    for _, marks in conftest.SLOW_FILES + conftest.SLOW_DIRECTORIES:
        used.update(marks)
    assert used <= declared, used - declared


def test_slow_entries_point_at_existing_paths() -> None:
    root = project_root()
    missing: list[str] = []
    for relative, _ in conftest.SLOW_FILES:
        if not (root / relative).is_file():
            missing.append(relative)
    for relative, _ in conftest.SLOW_DIRECTORIES:
        if not (root / relative).is_dir():
            missing.append(relative)
    assert not missing, f"в списке медленных тестов есть несуществующие пути: {missing}"


def test_slow_paths_are_inside_declared_testpaths() -> None:
    options = pytest_config()
    testpaths = [str(entry) for entry in options.get("testpaths", [])]
    orphans: list[str] = []
    for relative, _ in conftest.SLOW_FILES + conftest.SLOW_DIRECTORIES:
        if not any(relative == path or relative.startswith(path + "/") for path in testpaths):
            orphans.append(relative)
    assert not orphans, f"медленные пути вне testpaths: {orphans}"
