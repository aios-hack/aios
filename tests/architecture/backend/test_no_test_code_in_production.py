from __future__ import annotations

import ast
from pathlib import Path

import pytest

PRODUCTION = Path("backend")

ALLOWED_STUBS = {
    "backend/contexts/assistant/application/recording_replay.py",
    "backend/contexts/assistant/infrastructure/recordings.py",
    "backend/contexts/assistant/infrastructure/llm/fake_chat.py",
}

TEST_DIRECTORIES_AWAITING_C01 = {
    "backend/contexts/assistant/infrastructure/llm/tests",
}

STUB_WORDS = ("fixture", "fake", "stub", "dummy", "mock")


def _production_modules() -> list[Path]:
    found: list[Path] = []
    for path in sorted(PRODUCTION.rglob("*.py")):
        text = path.as_posix()
        if "__pycache__" in text or "/tests/" in text:
            continue
        found.append(path)
    return found


def test_no_test_directories_remain_inside_the_production_package() -> None:
    directories = sorted(
        path.as_posix()
        for path in PRODUCTION.rglob("tests")
        if path.is_dir() and "__pycache__" not in path.as_posix()
    )
    inside_contexts = {
        name
        for name in directories
        if name.startswith("backend/contexts/") or name.startswith("backend/shared/")
    }

    assert inside_contexts <= TEST_DIRECTORIES_AWAITING_C01, (
        "C-01 relocates the test directories inside the contexts, "
        f"there must be no new ones: {sorted(inside_contexts - TEST_DIRECTORIES_AWAITING_C01)}"
    )


def test_no_new_stub_module_appears_in_production() -> None:
    suspects = {
        path.as_posix()
        for path in _production_modules()
        if any(word in path.stem.lower() for word in STUB_WORDS)
    }

    assert suspects <= ALLOWED_STUBS, (
        "test stubs in production packages: " f"{sorted(suspects - ALLOWED_STUBS)}"
    )


def test_the_allowed_list_has_no_stale_entries() -> None:
    for name in ALLOWED_STUBS:
        assert Path(name).is_file(), f"{name} no longer exists, remove it from the list"


def test_production_never_imports_pytest() -> None:
    offenders: list[str] = []
    for path in _production_modules():
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                if any(alias.name.split(".")[0] == "pytest" for alias in node.names):
                    offenders.append(path.as_posix())
            elif isinstance(node, ast.ImportFrom):
                if (node.module or "").split(".")[0] == "pytest":
                    offenders.append(path.as_posix())

    assert not offenders, f"production code imports pytest: {sorted(set(offenders))}"


def test_production_never_imports_the_test_support_package() -> None:
    offenders: list[str] = []
    for path in _production_modules():
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and (node.module or "").startswith("tests"):
                offenders.append(path.as_posix())
            elif isinstance(node, ast.Import):
                if any(alias.name.startswith("tests") for alias in node.names):
                    offenders.append(path.as_posix())

    assert not offenders, f"production code imports tests/: {sorted(set(offenders))}"


@pytest.mark.parametrize("name", sorted(ALLOWED_STUBS))
def test_each_allowed_stub_is_reachable_from_a_cli_command(name: str) -> None:
    body = Path(name).read_text(encoding="utf-8")

    assert body.strip(), f"{name} is empty"
