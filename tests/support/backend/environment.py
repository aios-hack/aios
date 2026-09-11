from __future__ import annotations

import functools
import os
import shutil
import subprocess
from pathlib import Path


DOCS_ROOT_ENV_VAR = "AIOS_DOCS_ROOT"
BASE_RUN_ENV_VAR = "AIOS_BASE_RUN_DIR"


MODEL_Z_SCHEDULE_RELATIVE = Path("models") / "Model_Z" / "Model_Z_sch.inc"
CHDD_PYTHON_RELATIVE = Path("models") / "CHDD_PYTHON"
NORMATIVES_XLSX_RELATIVE = CHDD_PYTHON_RELATIVE / "input" / "Нормативы_ЧДД.xlsx"


def _candidate_roots() -> tuple[Path, ...]:
    from_env = os.environ.get(DOCS_ROOT_ENV_VAR)
    if from_env:
        return (Path(from_env),)
    root = repo_root()
    return tuple(
        candidate
        for parent in (root, root.parent, root.parent.parent)
        for candidate in (parent / "docs", parent / "docs-src")
    )


def docs_root() -> Path | None:
    for candidate in _candidate_roots():
        if (candidate / "models").is_dir():
            return candidate
    return None


def docs_path(relative: Path) -> Path | None:
    for root in _candidate_roots():
        resolved = root / relative
        if resolved.exists():
            return resolved
    return None


def model_z_schedule() -> Path | None:
    return docs_path(MODEL_Z_SCHEDULE_RELATIVE)


def model_z_dir() -> Path | None:
    return docs_path(Path("models") / "Model_Z")


def chdd_python_dir() -> Path | None:
    for root in _candidate_roots():
        candidate = root / CHDD_PYTHON_RELATIVE
        if (candidate / "chdd_model.py").is_file():
            return candidate
    return None


def normatives_xlsx() -> Path | None:
    return docs_path(NORMATIVES_XLSX_RELATIVE)


def repo_root() -> Path:
    here = Path(__file__).resolve()
    for parent in here.parents:
        if (parent / "pyproject.toml").is_file():
            return parent
    return here.parent


def _base_run_candidates() -> tuple[Path, ...]:
    from_env = os.environ.get(BASE_RUN_ENV_VAR)
    if from_env:
        return (Path(from_env).expanduser().resolve(),)
    root = repo_root()
    data_override = os.environ.get("AIOS_DATA_ROOT")
    data_dir = Path(data_override).expanduser().resolve() if data_override else root / "data"
    return (data_dir / "base_run",)


def base_run_dir() -> Path | None:
    for candidate in _base_run_candidates():
        if (candidate / "deck").is_dir() and (candidate / "runs").is_dir():
            return candidate
    return None


def base_run_missing_reason() -> str | None:
    if base_run_dir() is not None:
        return None
    expected = ", ".join(str(path) for path in _base_run_candidates())
    return (
        f"the base run is unavailable: no directory with 'deck/' and 'runs/' was found ({expected}). "
        f"Point to it with {BASE_RUN_ENV_VAR}; the search does not leave the repository."
    )


def base_run_output_dir() -> Path | None:
    root = base_run_dir()
    if root is None:
        return None
    runs = sorted(path for path in (root / "runs").iterdir() if path.is_dir())
    for run in reversed(runs):
        output = run / "output"
        if not output.is_dir():
            continue
        has_smspec = any(p.suffix.upper() == ".SMSPEC" for p in output.iterdir())
        has_unsmry = any(p.suffix.upper() == ".UNSMRY" for p in output.iterdir())
        if has_smspec and has_unsmry:
            return output
    return None


def missing_reason(what: str) -> str:
    return (
        f"{what} is unavailable: the organizers' data is not shipped with the code. "
        f"Point to the docs directory with {DOCS_ROOT_ENV_VAR} "
        f"or place it as a sibling of the code repository."
    )


@functools.lru_cache(maxsize=1)
def docker_unavailable_reason() -> str | None:
    binary = shutil.which("docker")
    if binary is None:
        return "Docker was not found in PATH: acceptance requires a real OPM Flow in a container"
    try:
        probe = subprocess.run(
            [binary, "info", "--format", "{{.ServerVersion}}"],
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=5.0,
        )
    except subprocess.TimeoutExpired:
        return "the Docker daemon did not respond within 5 seconds"
    if probe.returncode != 0:
        detail = (probe.stderr.strip() or probe.stdout.strip()).splitlines()
        tail = detail[-1] if detail else "no response from the daemon"
        return f"the Docker daemon is unavailable: {tail}"
    return None


__all__ = [
    "BASE_RUN_ENV_VAR",
    "DOCS_ROOT_ENV_VAR",
    "base_run_dir",
    "base_run_missing_reason",
    "base_run_output_dir",
    "chdd_python_dir",
    "docker_unavailable_reason",
    "docs_path",
    "docs_root",
    "missing_reason",
    "model_z_dir",
    "model_z_schedule",
    "normatives_xlsx",
    "repo_root",
]
