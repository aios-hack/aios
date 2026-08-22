"""Root scripts are production entry points, not pytest consumers."""

from __future__ import annotations

import ast
from pathlib import Path

from backend.core.paths import project_root


SCRIPTS = (
    Path("build_dataset.py"),
    Path("tools/g10_pool.py"),
    Path("tools/g10_run.py"),
    Path("tools/g10_violations.py"),
    Path("tools/g9_diff.py"),
    Path("tools/r1_check.py"),
)


def test_production_scripts_do_not_import_pytest_configuration() -> None:
    root = project_root()
    for relative in SCRIPTS:
        path = root / relative
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(path))
        imported = {
            alias.name
            for node in ast.walk(tree)
            for alias in getattr(node, "names", ())
            if isinstance(node, (ast.Import, ast.ImportFrom))
        }
        assert "conftest" not in imported, relative
        compile(source, str(path), "exec")
