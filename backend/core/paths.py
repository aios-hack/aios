"""Stable locations for project files and generated runtime artifacts."""

from __future__ import annotations

import os
from pathlib import Path


def project_root() -> Path:
    """Return the repository root without relying on a package's location."""
    override = os.environ.get("AIOS_PROJECT_ROOT")
    if override:
        return Path(override).expanduser().resolve()

    for parent in Path(__file__).resolve().parents:
        if (parent / "pyproject.toml").is_file():
            return parent
    raise RuntimeError("Could not find the AIOS project root")


def data_root() -> Path:
    """Return the location for OPM inputs, cache, and generated artifacts."""
    override = os.environ.get("AIOS_DATA_ROOT")
    if override:
        return Path(override).expanduser().resolve()
    return project_root() / "data"


def out_root() -> Path:
    """Return the root for generated human-facing results."""
    override = os.environ.get("AIOS_OUT_DIR")
    if override:
        return Path(override).expanduser().resolve()
    return project_root() / "out"
