from __future__ import annotations

import argparse
import importlib.util
import json
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path

from backend.shared.hashing import content_hash, hash_schedule
from backend.shared.paths import project_root
from backend.contexts.schedule.domain.build import ScheduleBuildError, build_schedule
from backend.contexts.schedule.domain.canonical import ScheduleCanonicalError, canonicalize
from backend.contexts.schedule.domain.lossless import ScheduleParseError, parse_schedule
from backend.contexts.schedule.application.emit import WELLS_SCHEDULE_FILE_NAME

from backend.interfaces.cli.paths import (
    chdd_python_dir,
    docs_root,
    example_input_xlsx,
    model_z_schedule,
    normatives_xlsx,
)
from backend.interfaces.cli.runner import run as run_cli


CLI_MODULES = (
    "backend.interfaces.cli.npv",
    "backend.interfaces.cli.emit",
    "backend.interfaces.cli.web",
    "backend.interfaces.cli.run",
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
    return "yes" if present else "NO"


def _verdict(passed: bool) -> str:
    return "OK" if passed else "FAIL"


def _module_available(name: str) -> bool:
    return importlib.util.find_spec(name) is not None


def _read_claimed_bundle(path: Path) -> dict[str, object]:
    if not path.is_file():
        raise SubmissionCheckError(
            f"claimed values not found: {path} is missing. A submission bundle "
            f"without {CLAIMED_NPV_FILE_NAME} cannot be checked - it is unknown "
            "which number and which schedule are claimed. Assemble the bundle with "
            "`python -m backend.presentation.cli.run submit --run-id <id>`."
        )
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError as error:
        raise SubmissionCheckError(f"{path} is not readable: {error}") from error
    try:
        loaded = json.loads(raw)
    except ValueError as error:
        raise SubmissionCheckError(
            f"{path} does not parse as JSON: {error}"
        ) from error
    if not isinstance(loaded, dict):
        raise SubmissionCheckError(
            f"{path}: expected an object with the claimed values, got "
            f"{type(loaded).__name__}"
        )
    for field in (CLAIMED_CANONICAL_FIELD, CLAIMED_CONTENT_FIELD):
        value = loaded.get(field)
        if not isinstance(value, str) or not value.strip():
            raise SubmissionCheckError(
                f"{path}: field {field} must be a non-empty string, got "
                f"{value!r} - there is nothing to compare against"
            )
    return loaded


def _read_submitted_bytes(path: Path) -> bytes:
    if not path.is_file():
        raise SubmissionCheckError(
            f"submitted file not found: {path} is missing from the bundle"
        )
    try:
        return path.read_bytes()
    except OSError as error:
        raise SubmissionCheckError(f"{path} is not readable: {error}") from error


def _canonical_hash_of(raw: bytes, path: Path) -> str:
    try:
        parsed = parse_schedule(raw)
    except ScheduleParseError as error:
        raise SubmissionCheckError(
            f"{path} does not parse as a schedule: {error}"
        ) from error
    try:
        schedule = build_schedule(parsed, raw)
    except ScheduleBuildError as error:
        raise SubmissionCheckError(
            f"{path} does not build into a Schedule: {error}"
        ) from error
    try:
        return hash_schedule(canonicalize(schedule))
    except ScheduleCanonicalError as error:
        raise SubmissionCheckError(
            f"{path} does not canonicalize: {error}"
        ) from error


def check_submission(directory: Path) -> list[CheckLine]:
    if not directory.is_dir():
        raise SubmissionCheckError(f"submission bundle directory not found: {directory}")
    schedule_path = directory / WELLS_SCHEDULE_FILE_NAME
    claimed = _read_claimed_bundle(directory / CLAIMED_NPV_FILE_NAME)
    raw = _read_submitted_bytes(schedule_path)
    history_path = directory / "validation" / "history.inc"
    history = history_path.read_bytes() if history_path.is_file() else b""
    actual_canonical = _canonical_hash_of(history + raw, schedule_path)
    actual_content = content_hash(raw)
    claimed_canonical = str(claimed[CLAIMED_CANONICAL_FIELD])
    claimed_content = str(claimed[CLAIMED_CONTENT_FIELD])
    lines = [
        CheckLine(
            "canonical schedule hash",
            actual_canonical == claimed_canonical,
            f"claimed {claimed_canonical}, recomputed {actual_canonical}",
        ),
        CheckLine(
            "file content hash",
            actual_content == claimed_content,
            f"claimed {claimed_content}, recomputed {actual_content} "
            f"({len(raw)} bytes)",
        ),
    ]
    return lines


def _print_submission(directory: Path) -> int:
    print(f"Submission bundle: {directory}")
    try:
        lines = check_submission(directory)
    except SubmissionCheckError as error:
        print(f"REFUSED: {error}")
        return 2
    for line in lines:
        print(f"  {line.name:<32} {_verdict(line.passed)}  {line.detail}")
    if all(line.passed for line in lines):
        print("\nThe bundle matches the claimed values: it can be submitted.")
        return 0
    print(
        "\nThe bundle does NOT match the claimed values: the submitted file differs "
        f"from the one {CLAIMED_NPV_FIELD} was computed for. It must not be submitted - "
        "reassemble the bundle with "
        "`python -m backend.presentation.cli.run submit --run-id <id>`."
    )
    return 1


def _print_environment() -> int:
    root = project_root()
    print(f"python:  {sys.version.split()[0]}")
    print(f"root:    {root}")

    print("\nBackend commands:")
    for module in CLI_MODULES:
        print(f"  {module:<36} {_mark(_module_available(module))}")

    frontend = root / "frontend" / "dist"
    print(f"\nBuilt frontend frontend/dist:  {_mark(frontend.is_dir())}")
    print(f"Docker for the OPM smoke test: {_mark(shutil.which('docker') is not None)}")

    print("\nOptional dependencies:")
    for name in OPTIONAL_DEPENDENCIES:
        print(f"  {name:<33} {_mark(_module_available(name))}")

    print("\nOrganizer data (mounted from outside, not part of the image):")
    root_docs = docs_root()
    print(f"  docs directory           {_mark(root_docs is not None)}  {root_docs or ''}")
    for label, path in (
        ("Model_Z_sch.inc deck", model_z_schedule()),
        ("CHDD_PYTHON calculator", chdd_python_dir()),
        ("NPV normatives xlsx", normatives_xlsx()),
        ("example input xlsx", example_input_xlsx()),
    ):
        print(f"  {label:<25}{_mark(path is not None)}  {path or ''}")

    if root_docs is None:
        print(
            "\nOrganizer data is not mounted: this is normal for a clean image. "
            "To run calculations, mount docs at /data/docs:ro."
        )
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="selfcheck",
        description="Check the environment and the submission bundle",
    )
    parser.add_argument(
        "--submission",
        type=Path,
        default=None,
        help=(
            "submission bundle directory: checks "
            f"{WELLS_SCHEDULE_FILE_NAME} against the hashes from {CLAIMED_NPV_FILE_NAME}"
        ),
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    options = build_parser().parse_args(argv)
    if options.submission is not None:
        return _print_submission(options.submission)
    return _print_environment()


if __name__ == "__main__":
    raise SystemExit(run_cli(main))
