from __future__ import annotations

import os
import platform
import subprocess
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path

DEFAULT_OPM_IMAGE = "openporousmedia/opmreleases:latest"
OPM_IMAGE_ENV = "OPM_FLOW_IMAGE"

TRACKED_PACKAGES: tuple[str, ...] = (
    "numpy",
    "torch",
    "openpyxl",
    "pytest",
)

_GIT_TIMEOUT_SECONDS = 10


def _run_git(args: list[str], root: Path | None) -> str | None:
    cwd = Path(root) if root is not None else Path(__file__).resolve().parent
    if not Path(cwd).is_dir():
        return None
    try:
        completed = subprocess.run(
            ["git", *args],
            cwd=str(cwd),
            capture_output=True,
            text=True,
            timeout=_GIT_TIMEOUT_SECONDS,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if completed.returncode != 0:
        return None
    return completed.stdout


def git_commit(root: Path | None = None) -> str | None:
    output = _run_git(["rev-parse", "HEAD"], root)
    if output is None:
        return None
    commit = output.strip()
    return commit or None


def git_dirty(root: Path | None = None) -> bool | None:
    if git_commit(root) is None:
        return None
    output = _run_git(["status", "--porcelain"], root)
    if output is None:
        return None
    return bool(output.strip())


def opm_image() -> str:
    value = os.environ.get(OPM_IMAGE_ENV, "").strip()
    return value or DEFAULT_OPM_IMAGE


def python_version() -> str:
    return platform.python_version()


def package_versions() -> dict[str, str]:
    versions: dict[str, str] = {}
    for name in TRACKED_PACKAGES:
        try:
            versions[name] = version(name)
        except PackageNotFoundError:
            continue
    return versions
