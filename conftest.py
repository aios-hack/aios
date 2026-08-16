from __future__ import annotations

import os
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
    here = Path(__file__).resolve()
    return tuple(parent / "docs" for parent in here.parents[0:3])


def docs_root() -> Path | None:
    for candidate in _candidate_roots():
        if (candidate / "models").is_dir():
            return candidate
    return None


def docs_path(relative: Path) -> Path | None:
    root = docs_root()
    if root is None:
        return None
    resolved = root / relative
    return resolved if resolved.exists() else None


def model_z_schedule() -> Path | None:
    return docs_path(MODEL_Z_SCHEDULE_RELATIVE)


def chdd_python_dir() -> Path | None:
    return docs_path(CHDD_PYTHON_RELATIVE)


def normatives_xlsx() -> Path | None:
    return docs_path(NORMATIVES_XLSX_RELATIVE)


def base_run_dir() -> Path | None:
    from_env = os.environ.get(BASE_RUN_ENV_VAR)
    candidates: tuple[Path, ...]
    if from_env:
        candidates = (Path(from_env),)
    else:
        here = Path(__file__).resolve()
        candidates = tuple(
            sibling / "data" / "base_run"
            for parent in here.parents[1:3]
            for sibling in parent.iterdir()
            if sibling.is_dir()
        )
    for candidate in candidates:
        if (candidate / "deck").is_dir() and (candidate / "runs").is_dir():
            return candidate
    return None


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
        f"{what} недоступен: данные организаторов не поставляются с кодом. "
        f"Укажите каталог docs через {DOCS_ROOT_ENV_VAR} "
        f"или разместите его сиблингом кодовой репы."
    )
