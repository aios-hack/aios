
from __future__ import annotations

import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2] / "backend"

REMOVED_PACKAGES: tuple[str, ...] = (
    "backend.application",
    "backend.core",
    "backend.domain",
    "backend.infrastructure",
    "backend.ml",
    "backend.presentation",
)


def imported_modules(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module is not None:
            modules.add(node.module)
    return modules


def test_removed_legacy_packages_are_gone() -> None:
    assert ROOT.is_dir(), f"backend package directory is missing: {ROOT}"
    present = sorted(
        name.split(".", 1)[1]
        for name in REMOVED_PACKAGES
        if (ROOT / name.split(".", 1)[1]).is_dir()
    )
    assert not present, f"legacy shim packages still on disk: {present}"


def test_no_module_imports_a_removed_legacy_package() -> None:
    assert ROOT.is_dir(), f"backend package directory is missing: {ROOT}"
    assert any(ROOT.rglob("*.py")), f"backend package directory is empty: {ROOT}"
    offenders: list[str] = []
    for path in ROOT.rglob("*.py"):
        if "tests" in path.parts:
            continue
        bad = sorted(
            module
            for module in imported_modules(path)
            if any(
                module == prefix or module.startswith(prefix + ".")
                for prefix in REMOVED_PACKAGES
            )
        )
        if bad:
            offenders.append(f"{path.relative_to(ROOT)}: {bad}")
    assert not offenders, f"imports of removed packages: {offenders}"


def test_production_code_does_not_import_test_configuration() -> None:
    assert ROOT.is_dir(), f"backend package directory is missing: {ROOT}"
    offenders = []
    for path in ROOT.rglob("*.py"):
        if "tests" in path.parts:
            continue
        if "conftest" in imported_modules(path):
            offenders.append(str(path.relative_to(ROOT)))
    assert not offenders, f"production code imports conftest: {offenders}"
