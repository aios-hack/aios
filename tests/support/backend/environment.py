from __future__ import annotations

import functools
import os
import shutil
import subprocess
from pathlib import Path

import pytest

DOCS_ROOT_ENV_VAR = "AIOS_DOCS_ROOT"
BASE_RUN_ENV_VAR = "AIOS_BASE_RUN_DIR"

SLOW_DIRECTORIES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("backend/domain/schedule/tests", ("slow",)),
    ("backend/presentation/ui_export/tests", ("slow", "showcase")),
)

SLOW_FILES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("backend/infrastructure/opm/tests/test_submission.py", ("slow", "opm")),
    ("backend/infrastructure/opm/tests/test_base_run.py", ("slow", "opm")),
    ("backend/infrastructure/opm/tests/test_cache.py", ("slow", "opm")),
    ("backend/infrastructure/opm/tests/test_runner.py", ("slow", "opm")),
    ("backend/infrastructure/opm/tests/test_response_loader.py", ("slow", "opm")),
    ("backend/infrastructure/opm/tests/test_opm_deck.py", ("slow", "opm")),
    ("backend/infrastructure/opm/tests/test_dataset_opm.py", ("slow", "opm")),
    ("backend/infrastructure/opm/tests/test_dataset.py", ("slow",)),
    ("backend/infrastructure/opm/tests/test_dataset_plan.py", ("slow",)),
    ("backend/infrastructure/opm/tests/test_dataset_compaction.py", ("slow",)),
    ("backend/domain/connectivity/tests/test_doe.py", ("slow",)),
    ("backend/domain/connectivity/tests/test_campaign.py", ("slow",)),
    ("backend/ml/surrogate/tests/test_crm.py", ("slow",)),
    ("backend/core/contracts/tests/test_hash_canon.py", ("slow",)),
    (
        "backend/application/optimization/tests/test_ensemble_spread_and_risk_selection.py",
        ("slow",),
    ),
)


def _marks_for(relative: str) -> tuple[str, ...]:
    for name, marks in SLOW_FILES:
        if relative == name:
            return marks
    for name, marks in SLOW_DIRECTORIES:
        if relative.startswith(name + "/"):
            return marks
    return ()


def pytest_collection_modifyitems(
    config: pytest.Config, items: list[pytest.Item]
) -> None:
    root = repo_root()
    for item in items:
        try:
            relative = Path(str(item.fspath)).resolve().relative_to(root).as_posix()
        except ValueError:
            continue
        for mark in _marks_for(relative):
            item.add_marker(getattr(pytest.mark, mark))


MODEL_Z_SCHEDULE_RELATIVE = Path("models") / "Model_Z" / "Model_Z_sch.inc"
CHDD_PYTHON_RELATIVE = Path("models") / "CHDD_PYTHON"
NORMATIVES_XLSX_RELATIVE = CHDD_PYTHON_RELATIVE / "input" / "Нормативы_ЧДД.xlsx"


def _candidate_roots() -> tuple[Path, ...]:
    from_env = os.environ.get(DOCS_ROOT_ENV_VAR)
    if from_env:
        return (Path(from_env),)
    here = Path(__file__).resolve()
    return tuple(
        candidate
        for parent in here.parents[0:3]
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
        f"базовый прогон недоступен: не найден каталог с 'deck/' и 'runs/' ({expected}). "
        f"Укажите его через {BASE_RUN_ENV_VAR}; поиск не выходит за пределы репозитория."
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
        f"{what} недоступен: данные организаторов не поставляются с кодом. "
        f"Укажите каталог docs через {DOCS_ROOT_ENV_VAR} "
        f"или разместите его сиблингом кодовой репы."
    )


@functools.lru_cache(maxsize=1)
def docker_unavailable_reason() -> str | None:
    binary = shutil.which("docker")
    if binary is None:
        return "Docker не найден в PATH: приёмка требует настоящего OPM Flow в контейнере"
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
        return "демон Docker не ответил за 5 секунд"
    if probe.returncode != 0:
        detail = (probe.stderr.strip() or probe.stdout.strip()).splitlines()
        tail = detail[-1] if detail else "нет ответа от демона"
        return f"демон Docker недоступен: {tail}"
    return None
