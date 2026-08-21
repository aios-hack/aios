"""Guard the one-way dependency direction of the new backend package."""

from __future__ import annotations

import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2] / "src" / "aios_backend"

# These are legacy executable modules still being reached through their old
# ``python -m`` paths.  Their orchestration code will move behind the new CLI;
# the business functions in the same files remain domain code for now.
LEGACY_WORKFLOW_MODULES = {
    "domain/connectivity/campaign.py",
    "domain/connectivity/measure.py",
    "infrastructure/opm/submission_run.py",
    "infrastructure/opm/verification.py",
}

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
    "ml": ("aios_backend.application", "aios_backend.presentation"),
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
            if "tests" in path.parts:
                continue
            if str(path.relative_to(ROOT)) in LEGACY_WORKFLOW_MODULES:
                continue
            imports = imported_modules(path)
            bad = sorted(
                module
                for module in imports
                if any(module == prefix or module.startswith(prefix + ".") for prefix in forbidden)
            )
            assert not bad, f"{path.relative_to(ROOT)} imports higher layer: {bad}"
