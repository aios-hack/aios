from __future__ import annotations

import argparse
import importlib.util
import json
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path

from backend.core.contracts import content_hash, hash_schedule
from backend.core.paths import project_root
from backend.domain.schedule import (
    ScheduleBuildError,
    ScheduleCanonicalError,
    ScheduleParseError,
    build_schedule,
    canonicalize,
    parse_schedule,
)
from backend.domain.schedule.emit import WELLS_SCHEDULE_FILE_NAME

from .paths import (
    chdd_python_dir,
    docs_root,
    example_input_xlsx,
    model_z_schedule,
    normatives_xlsx,
)


CLI_MODULES = (
    "backend.presentation.cli.npv",
    "backend.presentation.cli.emit",
    "backend.presentation.cli.web",
    "backend.presentation.cli.run",
)
OPTIONAL_DEPENDENCIES = ("anthropic", "numpy", "torch")

CLAIMED_NPV_FILE_NAME = "claimed_npv.json"
CLAIMED_CANONICAL_FIELD = "canonical_schedule_hash"
CLAIMED_CONTENT_FIELD = "content_hash_submission"
CLAIMED_NPV_FIELD = "claimed_npv_rub"


class SubmissionCheckError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class CheckLine:
    name: str
    passed: bool
    detail: str


def _mark(present: bool) -> str:
    return "есть" if present else "НЕТ"


def _verdict(passed: bool) -> str:
    return "ОК" if passed else "ПРОВАЛ"


def _module_available(name: str) -> bool:
    return importlib.util.find_spec(name) is not None


def _read_claimed_bundle(path: Path) -> dict[str, object]:
    if not path.is_file():
        raise SubmissionCheckError(
            f"заявленные величины не найдены: {path} отсутствует. Пакет сдачи без "
            f"{CLAIMED_NPV_FILE_NAME} проверить нельзя — неизвестно, какое число "
            "и какое расписание заявлены. Соберите пакет командой "
            "`python -m backend.presentation.cli.run submit --run-id <id>`."
        )
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError as error:
        raise SubmissionCheckError(f"{path} не читается: {error}") from error
    try:
        loaded = json.loads(raw)
    except ValueError as error:
        raise SubmissionCheckError(
            f"{path} не разбирается как JSON: {error}"
        ) from error
    if not isinstance(loaded, dict):
        raise SubmissionCheckError(
            f"{path}: ожидался объект с заявленными величинами, получено "
            f"{type(loaded).__name__}"
        )
    for field in (CLAIMED_CANONICAL_FIELD, CLAIMED_CONTENT_FIELD):
        value = loaded.get(field)
        if not isinstance(value, str) or not value.strip():
            raise SubmissionCheckError(
                f"{path}: поле {field} обязано быть непустой строкой, получено "
                f"{value!r} — сверять не с чем"
            )
    return loaded


def _read_submitted_bytes(path: Path) -> bytes:
    if not path.is_file():
        raise SubmissionCheckError(
            f"сдаваемый файл не найден: {path} отсутствует в пакете"
        )
    try:
        return path.read_bytes()
    except OSError as error:
        raise SubmissionCheckError(f"{path} не читается: {error}") from error


def _canonical_hash_of(raw: bytes, path: Path) -> str:
    try:
        parsed = parse_schedule(raw)
    except ScheduleParseError as error:
        raise SubmissionCheckError(
            f"{path} не разбирается как расписание: {error}"
        ) from error
    try:
        schedule = build_schedule(parsed, raw)
    except ScheduleBuildError as error:
        raise SubmissionCheckError(
            f"{path} не собирается в Schedule: {error}"
        ) from error
    try:
        return hash_schedule(canonicalize(schedule))
    except ScheduleCanonicalError as error:
        raise SubmissionCheckError(
            f"{path} не канонизируется: {error}"
        ) from error


def check_submission(directory: Path) -> list[CheckLine]:
    if not directory.is_dir():
        raise SubmissionCheckError(f"каталог пакета сдачи не найден: {directory}")
    schedule_path = directory / WELLS_SCHEDULE_FILE_NAME
    claimed = _read_claimed_bundle(directory / CLAIMED_NPV_FILE_NAME)
    raw = _read_submitted_bytes(schedule_path)
    actual_canonical = _canonical_hash_of(raw, schedule_path)
    actual_content = content_hash(raw)
    claimed_canonical = str(claimed[CLAIMED_CANONICAL_FIELD])
    claimed_content = str(claimed[CLAIMED_CONTENT_FIELD])
    lines = [
        CheckLine(
            "канонический хеш расписания",
            actual_canonical == claimed_canonical,
            f"заявлен {claimed_canonical}, пересчитан {actual_canonical}",
        ),
        CheckLine(
            "хеш содержимого файла",
            actual_content == claimed_content,
            f"заявлен {claimed_content}, пересчитан {actual_content} "
            f"({len(raw)} байт)",
        ),
    ]
    return lines


def _print_submission(directory: Path) -> int:
    print(f"Пакет сдачи: {directory}")
    try:
        lines = check_submission(directory)
    except SubmissionCheckError as error:
        print(f"ОТКАЗ: {error}")
        return 2
    for line in lines:
        print(f"  {line.name:<32} {_verdict(line.passed)}  {line.detail}")
    if all(line.passed for line in lines):
        print("\nПакет соответствует заявленным величинам: сдавать можно.")
        return 0
    print(
        "\nПакет НЕ соответствует заявленным величинам: сдаваемый файл отличается "
        f"от того, для которого посчитан {CLAIMED_NPV_FIELD}. Сдавать нельзя — "
        "пересоберите пакет командой "
        "`python -m backend.presentation.cli.run submit --run-id <id>`."
    )
    return 1


def _print_environment() -> int:
    root = project_root()
    print(f"python:  {sys.version.split()[0]}")
    print(f"корень:  {root}")

    print("\nКоманды backend:")
    for module in CLI_MODULES:
        print(f"  {module:<36} {_mark(_module_available(module))}")

    frontend = root / "frontend" / "dist"
    print(f"\nСобранный фронт frontend/dist: {_mark(frontend.is_dir())}")
    print(f"Docker для OPM smoke:           {_mark(shutil.which('docker') is not None)}")

    print("\nОпциональные зависимости:")
    for name in OPTIONAL_DEPENDENCIES:
        print(f"  {name:<33} {_mark(_module_available(name))}")

    print("\nДанные организаторов (монтируются снаружи, в образ не входят):")
    root_docs = docs_root()
    print(f"  каталог docs             {_mark(root_docs is not None)}  {root_docs or ''}")
    for label, path in (
        ("дек Model_Z_sch.inc", model_z_schedule()),
        ("расчётчик CHDD_PYTHON", chdd_python_dir()),
        ("Нормативы_ЧДД.xlsx", normatives_xlsx()),
        ("Пример_исходных_данных", example_input_xlsx()),
    ):
        print(f"  {label:<25}{_mark(path is not None)}  {path or ''}")

    if root_docs is None:
        print(
            "\nДанные организаторов не смонтированы: это нормально для чистого "
            "образа. Для расчёта смонтируйте docs в /data/docs:ro."
        )
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="selfcheck",
        description="Проверка окружения и пакета сдачи",
    )
    parser.add_argument(
        "--submission",
        type=Path,
        default=None,
        help=(
            "каталог пакета сдачи: сверяет "
            f"{WELLS_SCHEDULE_FILE_NAME} с хешами из {CLAIMED_NPV_FILE_NAME}"
        ),
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    options = build_parser().parse_args(argv)
    if options.submission is not None:
        return _print_submission(options.submission)
    return _print_environment()


if __name__ == "__main__":
    raise SystemExit(main())
