from __future__ import annotations

import ast
from pathlib import Path

from backend.shared.paths import project_root

SCRIPT_DIRECTORIES: tuple[str, ...] = ("tools", "scripts")


def discovered_scripts() -> tuple[Path, ...]:
    root = project_root()
    found: list[Path] = [Path("build_dataset.py")]
    for directory in SCRIPT_DIRECTORIES:
        base = root / directory
        if not base.is_dir():
            continue
        for path in sorted(base.rglob("*.py")):
            if "__pycache__" in path.parts or "tests" in path.parts:
                continue
            found.append(path.relative_to(root))
    return tuple(found)


def imported_modules(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module is not None:
            modules.add(node.module)
    return modules


def test_scripts_are_discovered_automatically() -> None:
    scripts = discovered_scripts()
    assert scripts, "no entry-point script was found"
    names = {path.as_posix() for path in scripts}
    assert "tools/lambda_compare.py" in names, sorted(names)


def test_production_scripts_do_not_import_pytest_configuration() -> None:
    root = project_root()
    offenders: list[str] = []
    for relative in discovered_scripts():
        path = root / relative
        source = path.read_text(encoding="utf-8")
        compile(source, str(path), "exec")
        if "conftest" in imported_modules(path):
            offenders.append(relative.as_posix())
    assert not offenders, f"scripts import the pytest configuration: {offenders}"
