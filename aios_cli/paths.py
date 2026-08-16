from __future__ import annotations

import os
from pathlib import Path

DOCS_ROOT_ENV_VAR = "AIOS_DOCS_ROOT"
SEED_ENV_VAR = "AIOS_SEED"
DEFAULT_SEED = 20260816

MODEL_Z_SCHEDULE_RELATIVE = Path("models") / "Model_Z" / "Model_Z_sch.inc"
CHDD_PYTHON_RELATIVE = Path("models") / "CHDD_PYTHON"
NORMATIVES_XLSX_RELATIVE = CHDD_PYTHON_RELATIVE / "input" / "Нормативы_ЧДД.xlsx"
EXAMPLE_INPUT_RELATIVE = CHDD_PYTHON_RELATIVE / "input" / "Пример_исходных_данных.xlsx"


def _candidate_roots() -> tuple[Path, ...]:
    from_env = os.environ.get(DOCS_ROOT_ENV_VAR)
    if from_env:
        return (Path(from_env),)
    here = Path(__file__).resolve()
    return tuple(parent / "docs" for parent in here.parents[1:4])


def docs_root() -> Path | None:
    for candidate in _candidate_roots():
        if (candidate / "models").is_dir():
            return candidate
    return None


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
    raw = os.environ.get(SEED_ENV_VAR)
    if raw is None or not raw.strip():
        return DEFAULT_SEED
    try:
        return int(raw)
    except ValueError as error:
        raise SystemExit(
            f"{SEED_ENV_VAR}={raw!r} — не целое число"
        ) from error


def require(path: Path | None, what: str) -> Path:
    if path is None:
        raise SystemExit(
            f"{what} недоступен: данные организаторов не поставляются с образом. "
            f"Смонтируйте каталог docs и укажите {DOCS_ROOT_ENV_VAR} "
            f"(в образе — /data/docs)."
        )
    return path
