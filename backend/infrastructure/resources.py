"""Locations of organizer-supplied files used by runtime workflows."""

from __future__ import annotations

import os
from pathlib import Path

from backend.core.paths import project_root

DOCS_ROOT_ENV_VAR = "AIOS_DOCS_ROOT"


def _candidate_docs_roots() -> tuple[Path, ...]:
    configured = os.environ.get(DOCS_ROOT_ENV_VAR)
    if configured:
        return (Path(configured),)
    workspace = project_root().parent
    return (workspace / "docs", workspace / "docs-src")


def find_docs_root() -> Path | None:
    for candidate in _candidate_docs_roots():
        if (candidate / "models").is_dir():
            return candidate
    return None


def docs_root() -> Path:
    found = find_docs_root()
    if found is not None:
        return found
    raise FileNotFoundError(
        f"Organizer docs not found. Set {DOCS_ROOT_ENV_VAR} to their directory."
    )


def model_z_dir() -> Path:
    return docs_root() / "models" / "Model_Z"


def chdd_python_dir() -> Path:
    for root in _candidate_docs_roots():
        candidate = root / "models" / "CHDD_PYTHON"
        if (candidate / "chdd_model.py").is_file():
            return candidate
    raise FileNotFoundError(
        f"Organizer CHDD_PYTHON not found. Set {DOCS_ROOT_ENV_VAR} to its docs directory."
    )


def normatives_xlsx() -> Path:
    path = chdd_python_dir() / "input" / "Нормативы_ЧДД.xlsx"
    if not path.is_file():
        raise FileNotFoundError(f"Organizer normatives not found: {path}")
    return path
