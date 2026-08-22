"""Locations of organizer-supplied files used by runtime workflows."""

from __future__ import annotations

import os
from pathlib import Path

from backend.core.paths import project_root

DOCS_ROOT_ENV_VAR = "AIOS_DOCS_ROOT"


def find_docs_root() -> Path | None:
    configured = os.environ.get(DOCS_ROOT_ENV_VAR)
    candidates = (Path(configured),) if configured else (project_root().parent / "docs",)
    for candidate in candidates:
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
    return docs_root() / "models" / "CHDD_PYTHON"


def normatives_xlsx() -> Path:
    path = chdd_python_dir() / "input" / "Нормативы_ЧДД.xlsx"
    if not path.is_file():
        raise FileNotFoundError(f"Organizer normatives not found: {path}")
    return path
