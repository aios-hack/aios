from __future__ import annotations

import ast
import tomllib
from pathlib import Path

import pytest

from backend.shared.paths import project_root

REQUIRED_MARKERS: tuple[str, ...] = ("slow", "opm", "showcase")


def pytest_config() -> dict[str, object]:
    text = (project_root() / "pyproject.toml").read_text(encoding="utf-8")
    return tomllib.loads(text)["tool"]["pytest"]["ini_options"]


def declared_markers() -> set[str]:
    options = pytest_config()
    return {str(entry).split(":", 1)[0].strip() for entry in options.get("markers", [])}


def collected_test_files() -> list[Path]:
    found: list[Path] = []
    for path in sorted(Path("tests").rglob("test_*.py")):
        if "__pycache__" not in path.as_posix():
            found.append(path)
    return found


def marks_used_in(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    used: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Attribute):
            inner = node.value
            if isinstance(inner.value, ast.Name) and inner.value.id == "pytest":
                if inner.attr == "mark":
                    used.add(node.attr)
    return used


def test_default_run_excludes_the_slow_group() -> None:
    addopts = pytest_config().get("addopts", "")

    assert "not slow" in str(addopts), addopts


def test_the_required_markers_are_declared() -> None:
    assert set(REQUIRED_MARKERS) <= declared_markers()


def test_every_marker_used_by_a_test_is_declared() -> None:
    declared = declared_markers()
    builtin = {"parametrize", "skipif", "skip", "xfail", "usefixtures", "filterwarnings"}
    undeclared: dict[str, set[str]] = {}
    for path in collected_test_files():
        used = marks_used_in(path) - builtin - declared
        if used:
            undeclared[path.as_posix()] = used

    assert not undeclared, f"undeclared markers: {undeclared}"


def test_the_slow_group_is_marked_by_decorators_not_by_a_path_list() -> None:
    for name in ("conftest.py", "tests/conftest.py", "tests/support/backend/environment.py"):
        path = project_root() / name
        if not path.is_file():
            continue
        body = path.read_text(encoding="utf-8")
        assert "SLOW_FILES" not in body, f"{name}: the manual list of slow files must be removed"
        assert "SLOW_DIRECTORIES" not in body, name


def test_the_root_conftest_no_longer_holds_utilities() -> None:
    assert not (project_root() / "conftest.py").is_file(), (
        "the utilities moved to tests/support/backend, the root conftest.py is not needed"
    )


@pytest.mark.parametrize("marker", REQUIRED_MARKERS)
def test_each_required_marker_is_actually_used(marker: str) -> None:
    users = [path.as_posix() for path in collected_test_files() if marker in marks_used_in(path)]

    assert users, f"marker {marker} is declared but used by no test"


def test_testpaths_are_the_two_roots_and_they_exist() -> None:
    testpaths = [str(entry) for entry in pytest_config().get("testpaths", [])]

    assert testpaths == ["tests/backend", "tests/architecture"], testpaths
    for path in testpaths:
        assert Path(path).is_dir(), path


def test_no_test_lives_outside_the_shared_tests_root() -> None:
    strays = [
        path.as_posix()
        for path in Path("backend").rglob("test_*.py")
        if "__pycache__" not in path.as_posix()
    ]

    assert not strays, f"tests inside the production package: {strays}"
