from __future__ import annotations

import os
from pathlib import Path

DOCS_ROOT_ENV_VAR = "AIOS_DOCS_ROOT"

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


def model_z_dir() -> Path | None:
    return docs_path(Path("models") / "Model_Z")


def chdd_python_dir() -> Path | None:
    return docs_path(CHDD_PYTHON_RELATIVE)


def normatives_xlsx() -> Path | None:
    return docs_path(NORMATIVES_XLSX_RELATIVE)


def missing_reason(what: str) -> str:
    return (
        f"{what} недоступен: данные организаторов не поставляются с кодом. "
        f"Укажите каталог docs через {DOCS_ROOT_ENV_VAR} "
        f"или разместите его сиблингом кодовой репы."
    )
