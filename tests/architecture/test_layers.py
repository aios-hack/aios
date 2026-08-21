"""Guard the one-way dependency direction of the new backend package."""

from __future__ import annotations

import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2] / "src" / "aios_backend"

FORBIDDEN: dict[str, tuple[str, ...]] = {
    "core": (
        "aios_backend.domain",
        "aios_backend.ml",
        "aios_backend.infrastructure",
        "aios_backend.application",
        "aios_backend.presentation",
    ),
    "domain": (
        "aios_backend.ml",
        "aios_backend.infrastructure",
        "aios_backend.application",
        "aios_backend.presentation",
    ),
    "ml": (
        "aios_backend.infrastructure",
        "aios_backend.application",
        "aios_backend.presentation",
    ),
    "infrastructure": ("aios_backend.application", "aios_backend.presentation"),
    "application": ("aios_backend.presentation",),
}


def imported_modules(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module is not None:
            modules.add(node.module)
    return modules


def test_backend_layers_only_depend_downward() -> None:
    for layer, forbidden in FORBIDDEN.items():
        for path in (ROOT / layer).rglob("*.py"):
            imports = imported_modules(path)
            bad = sorted(
                module
                for module in imports
                if any(module == prefix or module.startswith(prefix + ".") for prefix in forbidden)
            )
            assert not bad, f"{path.relative_to(ROOT)} imports higher layer: {bad}"
