from __future__ import annotations

import ast
from pathlib import Path

import pytest

PRODUCTION = Path("backend")

ALLOWED_ENV_READERS = {
    "backend/shared/settings.py",
    "backend/shared/paths.py",
}

KNOWN_ENV_DEBT = {
    "backend/contexts/assistant/infrastructure/llm/client.py",
    "backend/contexts/assistant/infrastructure/llm/provider.py",
    "backend/contexts/assistant/infrastructure/stt.py",
    "backend/contexts/optimization/application/search_use_case.py",
    "backend/contexts/optimization/infrastructure/artifacts.py",
    "backend/contexts/runs/infrastructure/worker_process.py",
    "backend/contexts/simulation/infrastructure/runner.py",
    "backend/interfaces/cli/surrogate/screen_verify.py",
    "backend/interfaces/cli/web_run_worker.py",
}


def _production_modules() -> list[Path]:
    found: list[Path] = []
    for path in sorted(PRODUCTION.rglob("*.py")):
        text = path.as_posix()
        if "__pycache__" in text or "/tests/" in text:
            continue
        found.append(path)
    return found


def _env_reads(path: Path) -> list[int]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    hits: list[int] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name):
            if node.value.id == "os" and node.attr in ("environ", "getenv"):
                hits.append(node.lineno)
    return hits


def test_no_module_reads_the_environment_while_being_imported() -> None:
    offenders: list[str] = []
    for path in _production_modules():
        if path.as_posix() in ALLOWED_ENV_READERS:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in tree.body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                continue
            for sub in ast.walk(node):
                if isinstance(sub, ast.Attribute) and isinstance(sub.value, ast.Name):
                    if sub.value.id == "os" and sub.attr in ("environ", "getenv"):
                        offenders.append(f"{path.as_posix()}:{node.lineno}")
                        break
    assert not offenders, (
        "чтение окружения на импорте делает импорт зависимым от среды: "
        f"{sorted(set(offenders))}"
    )


def test_the_environment_debt_does_not_grow() -> None:
    readers = {
        path.as_posix()
        for path in _production_modules()
        if path.as_posix() not in ALLOWED_ENV_READERS and _env_reads(path)
    }

    assert readers <= KNOWN_ENV_DEBT, (
        "новые чтения os.environ вне Settings: "
        f"{sorted(readers - KNOWN_ENV_DEBT)}"
    )


def test_the_debt_list_has_no_stale_entries() -> None:
    readers = {
        path.as_posix()
        for path in _production_modules()
        if _env_reads(path)
    }

    assert KNOWN_ENV_DEBT <= readers, (
        "долг закрыт, уберите из списка: " f"{sorted(KNOWN_ENV_DEBT - readers)}"
    )


@pytest.mark.parametrize("name", sorted(ALLOWED_ENV_READERS))
def test_the_allowed_readers_still_exist(name: str) -> None:
    assert Path(name).is_file()
