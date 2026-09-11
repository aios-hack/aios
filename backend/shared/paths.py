from __future__ import annotations

import os
from pathlib import Path
from typing import Mapping

PROJECT_ROOT_ENV_VAR = "AIOS_PROJECT_ROOT"
DATA_ROOT_ENV_VAR = "AIOS_DATA_ROOT"
OUT_ROOT_ENV_VAR = "AIOS_OUT_DIR"
DOCS_ROOT_ENV_VAR = "AIOS_DOCS_ROOT"


def _override(environ: Mapping[str, str], name: str) -> Path | None:
    value = environ.get(name)
    if not value:
        return None
    return Path(value).expanduser().resolve()


def project_root(environ: Mapping[str, str] | None = None) -> Path:
    source = os.environ if environ is None else environ
    override = _override(source, PROJECT_ROOT_ENV_VAR)
    if override is not None:
        return override
    for parent in Path(__file__).resolve().parents:
        if (parent / "pyproject.toml").is_file():
            return parent
    raise RuntimeError("Could not find the AIOS project root")


def repository_root(fallback: Path | None = None) -> Path:
    for parent in Path(__file__).resolve().parents:
        if (parent / "pyproject.toml").is_file():
            return parent
    if fallback is not None:
        return fallback
    raise RuntimeError("Could not find the AIOS project root")


def data_root(environ: Mapping[str, str] | None = None) -> Path:
    source = os.environ if environ is None else environ
    override = _override(source, DATA_ROOT_ENV_VAR)
    if override is not None:
        return override
    return project_root(source) / "data"


def out_root(environ: Mapping[str, str] | None = None) -> Path:
    source = os.environ if environ is None else environ
    override = _override(source, OUT_ROOT_ENV_VAR)
    if override is not None:
        return override
    return project_root(source) / "out"


def docs_root_candidates(environ: Mapping[str, str] | None = None) -> tuple[Path, ...]:
    source = os.environ if environ is None else environ
    configured = source.get(DOCS_ROOT_ENV_VAR)
    if configured:
        return (Path(configured),)
    workspace = project_root(source).parent
    return (workspace / "docs", workspace / "docs-src")


__all__ = [
    "DATA_ROOT_ENV_VAR",
    "DOCS_ROOT_ENV_VAR",
    "OUT_ROOT_ENV_VAR",
    "PROJECT_ROOT_ENV_VAR",
    "data_root",
    "docs_root_candidates",
    "out_root",
    "project_root",
    "repository_root",
]
