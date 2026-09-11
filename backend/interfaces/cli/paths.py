from __future__ import annotations

from pathlib import Path

from backend.shared.resources import find_docs_root
from backend.shared.settings import Settings

DOCS_ROOT_ENV_VAR = "AIOS_DOCS_ROOT"
SEED_ENV_VAR = "AIOS_SEED"
DEFAULT_SEED = 20260816

MODEL_Z_SCHEDULE_RELATIVE = Path("models") / "Model_Z" / "Model_Z_sch.inc"
CHDD_PYTHON_RELATIVE = Path("models") / "CHDD_PYTHON"
NORMATIVES_XLSX_RELATIVE = CHDD_PYTHON_RELATIVE / "input" / "Нормативы_ЧДД.xlsx"
EXAMPLE_INPUT_RELATIVE = CHDD_PYTHON_RELATIVE / "input" / "Пример_исходных_данных.xlsx"


def _candidate_roots() -> tuple[Path, ...]:
    root = find_docs_root()
    return (root,) if root is not None else ()


def docs_root() -> Path | None:
    return find_docs_root()


def _docs_path(relative: Path) -> Path | None:
    root = docs_root()
    if root is None:
        return None
    resolved = root / relative
    return resolved if resolved.exists() else None


def model_z_schedule() -> Path | None:
    return _docs_path(MODEL_Z_SCHEDULE_RELATIVE)


def chdd_python_dir() -> Path | None:
    return _docs_path(CHDD_PYTHON_RELATIVE)


def normatives_xlsx() -> Path | None:
    return _docs_path(NORMATIVES_XLSX_RELATIVE)


def example_input_xlsx() -> Path | None:
    return _docs_path(EXAMPLE_INPUT_RELATIVE)


def default_seed() -> int:
    return Settings.from_env().seed


def require(path: Path | None, what: str) -> Path:
    if path is None:
        raise SystemExit(
            f"{what} is unavailable: organizer data does not ship with the image. "
            f"Mount the docs directory and set {DOCS_ROOT_ENV_VAR} "
            f"(inside the image it is /data/docs)."
        )
    return path
