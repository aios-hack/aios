from __future__ import annotations

import ast
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
CONTEXTS = ROOT / "backend" / "contexts"
SHARED = ROOT / "backend" / "shared"

DOMAIN_IMPORTS_APPLICATION_EXCEPTIONS: frozenset[str] = frozenset()
DOMAIN_IMPORTS_INFRASTRUCTURE_EXCEPTIONS: frozenset[str] = frozenset()


def imported_modules(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module is not None:
            modules.add(node.module)
    return modules


def _is_type_checking_test(test: ast.expr) -> bool:
    if isinstance(test, ast.Name):
        return test.id == "TYPE_CHECKING"
    if isinstance(test, ast.Attribute):
        return test.attr == "TYPE_CHECKING"
    return False


def runtime_imported_modules(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    guarded: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.If) and _is_type_checking_test(node.test):
            for inner in node.body:
                for child in ast.walk(inner):
                    guarded.add(id(child))
    modules: set[str] = set()
    for node in ast.walk(tree):
        if id(node) in guarded:
            continue
        if isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module is not None:
            modules.add(node.module)
    return modules


def layer_of(module: str) -> str | None:
    parts = module.split(".")
    if len(parts) < 4 or parts[0] != "backend" or parts[1] != "contexts":
        return None
    return parts[3]


def context_names() -> list[str]:
    return sorted(
        path.name
        for path in CONTEXTS.iterdir()
        if path.is_dir() and not path.name.startswith("__")
    )


def relative(path: Path) -> str:
    return path.relative_to(ROOT).as_posix()


@pytest.mark.parametrize("context", context_names())
def test_domain_never_imports_application(context: str) -> None:
    domain = CONTEXTS / context / "domain"
    if not domain.is_dir():
        pytest.skip(f"{context} has no domain layer")
    offenders: list[str] = []
    for path in sorted(domain.rglob("*.py")):
        name = relative(path)
        if name in DOMAIN_IMPORTS_APPLICATION_EXCEPTIONS:
            continue
        for module in sorted(imported_modules(path)):
            if layer_of(module) == "application":
                offenders.append(f"{name} -> {module}")
    assert not offenders, f"domain imports application: {offenders}"


@pytest.mark.parametrize("context", context_names())
def test_domain_never_imports_infrastructure(context: str) -> None:
    domain = CONTEXTS / context / "domain"
    if not domain.is_dir():
        pytest.skip(f"{context} has no domain layer")
    offenders: list[str] = []
    for path in sorted(domain.rglob("*.py")):
        name = relative(path)
        if name in DOMAIN_IMPORTS_INFRASTRUCTURE_EXCEPTIONS:
            continue
        for module in sorted(runtime_imported_modules(path)):
            if layer_of(module) == "infrastructure":
                offenders.append(f"{name} -> {module}")
    assert not offenders, f"domain imports infrastructure: {offenders}"


@pytest.mark.parametrize("context", context_names())
def test_domain_never_imports_a_private_symbol_across_contexts(context: str) -> None:
    domain = CONTEXTS / context / "domain"
    if not domain.is_dir():
        pytest.skip(f"{context} has no domain layer")
    offenders: list[str] = []
    for path in sorted(domain.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.ImportFrom) or node.module is None:
                continue
            parts = node.module.split(".")
            if len(parts) < 3 or parts[0] != "backend" or parts[1] != "contexts":
                continue
            if parts[2] == context:
                continue
            private = sorted(
                alias.name for alias in node.names if alias.name.startswith("_")
            )
            if private:
                offenders.append(f"{relative(path)} -> {node.module}: {private}")
    assert not offenders, f"domain imports private symbols across contexts: {offenders}"


def test_shared_never_imports_contexts_or_interfaces() -> None:
    offenders: list[str] = []
    for path in sorted(SHARED.rglob("*.py")):
        for module in sorted(imported_modules(path)):
            if module.startswith(("backend.contexts", "backend.interfaces")):
                offenders.append(f"{relative(path)} -> {module}")
    assert not offenders, f"shared reaches upward: {offenders}"
