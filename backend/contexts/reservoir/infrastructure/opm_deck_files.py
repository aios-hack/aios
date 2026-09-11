from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from backend.contexts.reservoir.domain.errors import OpmDeckError
from backend.contexts.schedule.domain.schedule import EventKind, FixedDeckEvent
from backend.contexts.schedule.domain.lossless import ParsedSchedule, parse_schedule
from backend.contexts.reservoir.infrastructure.summary import (
    RegionPlan,
    SummaryPlan,
    SummaryPlanError,
    _expand_integers,
    _keyword_payload,
)
from backend.shared.settings import Settings

_MODEL_DATA = "Model_Z.data"
_SCHEDULE_INCLUDE = "Model_Z_sch.inc"
_SUMMARY_INCLUDE = "Model_Z_summary.inc"
_REGIONS_INCLUDE = "Model_Z_regs.inc"
_INPUT_SUFFIXES = frozenset({".data", ".inc"})
_TOKEN_RE = re.compile(rb"'([^']*)'|([^\s/]+)")
_UTF8_BOM = b"\xef\xbb\xbf"
_OPM_UNSUPPORTED_GRID_KEYWORDS = (b"ARRZONE", b"ARRZONE_4")

DIAGNOSTIC_MARKER_NAME = "AIOS_DIAGNOSTIC_DECK"
DIAGNOSTIC_DECK_BANNER = (
    "-- AIOS DIAGNOSTIC DECK: NOT FOR SUBMISSION.\n"
    "-- FIPNUM is assembled from FIP_ZONE and RPR is requested per region so\n"
    "-- that regional pressure can be measured. The submitted deck carries\n"
    "-- neither array; a run of this deck is a measurement, not a delivery.\n"
)
DIAGNOSTIC_MARKER_TEXT = (
    "AIOS diagnostic deck.\n"
    "\n"
    "The deck is assembled to measure regional reservoir pressure: FIPNUM is assembled "
    "from FIP_ZONE and RPR is requested in SUMMARY for every marked-up region.\n"
    "\n"
    "This deck is not for submission. It does not change the submitted schedule - "
    "the control and fixed layers are the same, only the reporting differs.\n"
)


@dataclass(frozen=True, slots=True)
class EmittedOpmDeck:
    data_file: Path
    schedule_file: Path
    summary_file: Path
    summary_plan: SummaryPlan
    input_files: tuple[Path, ...]
    content_hash_opm: str
    diagnostic: bool = False
    region_plan: RegionPlan | None = None
    regions_file: Path | None = None
    diagnostic_marker_file: Path | None = None


@dataclass(frozen=True, slots=True)
class EmittedSchedule:
    raw: bytes
    content_hash: str
    model_dir: Path
    opm_schedule_source: Path | None


@dataclass(frozen=True, slots=True)
class _WellControl:
    well: str
    target_kind: EventKind
    value: float
    status: EventKind


def _block_records(raw_block: bytes) -> tuple[tuple[str, ...], ...]:
    records: list[tuple[str, ...]] = []
    lines = raw_block.splitlines()
    for line in lines[1:-1]:
        body = line.split(b"--", 1)[0].strip()
        if not body:
            continue
        if not body.endswith(b"/"):
            raise OpmDeckError(f"the block record does not end with '/': {body!r}")
        fields = []
        for match in _TOKEN_RE.finditer(body[:-1]):
            token = match.group(1) if match.group(1) is not None else match.group(2)
            try:
                fields.append(token.decode("ascii"))
            except UnicodeDecodeError as error:
                raise OpmDeckError("the WELSPECS identifier must be ASCII") from error
        records.append(tuple(fields))
    return tuple(records)


def _raw_keyword_block(raw: bytes, keyword: bytes) -> bytes:
    lines = raw.splitlines(keepends=True)
    matches: list[bytes] = []
    for index, line in enumerate(lines):
        if line.strip() != keyword:
            continue
        end = index + 1
        while end < len(lines) and lines[end].strip() != b"/":
            end += 1
        if end == len(lines):
            raise OpmDeckError(f"{keyword.decode()}: the block is not closed")
        matches.append(b"".join(lines[index : end + 1]))
    if len(matches) != 1:
        raise OpmDeckError(
            f"expected one {keyword.decode()} block, found {len(matches)}"
        )
    return matches[0]


def _strip_keyword_records(raw: bytes, keywords: tuple[bytes, ...]) -> bytes:
    lines = raw.splitlines(keepends=True)
    output: list[bytes] = []
    index = 0
    while index < len(lines):
        keyword = lines[index].strip()
        if keyword not in keywords:
            output.append(lines[index])
            index += 1
            continue
        start = index
        index += 1
        while index < len(lines) and lines[index].strip() != b"/":
            index += 1
        if index == len(lines):
            raise OpmDeckError(f"{keyword.decode()}: the block is not closed")
        index += 1
        output.append(
            b"-- OPM compatibility: removed tNavigator-only "
            + keyword
            + f" block from source lines {start + 1}..{index}.\n".encode("ascii")
        )
    return b"".join(output)


def _completion_activation_keys(parsed: ParsedSchedule) -> set[tuple[int, str]]:
    return {
        (event.control_step, event.well)
        for event in parsed.fixed_deck_events
        if event.operator in ("COMPDAT", "COMPDATMD")
    }


def _noncompletion_fixed_events(parsed: ParsedSchedule) -> tuple[FixedDeckEvent, ...]:
    return tuple(
        event
        for event in parsed.fixed_deck_events
        if event.operator not in ("COMPDAT", "COMPDATMD")
    )


def _resolve_opm_schedule_template(
    model_dir: Path,
    source_raw: bytes,
    source_parsed: ParsedSchedule,
) -> tuple[ParsedSchedule, Path | None]:
    has_md = any(block.keyword == "COMPDATMD" for block in source_parsed.blocks)
    has_tracks = re.search(rb"(?m)^WELLTRACK(?:\s|$)", source_raw) is not None
    if not has_md and not has_tracks:
        return source_parsed, None

    configured = Settings.from_env().compdat_model_dir
    candidates: list[Path] = []
    if configured is not None:
        candidates.append(configured)
    workspace = model_dir.parents[2] if len(model_dir.parents) >= 3 else model_dir.parent
    candidates.extend(
        (
            workspace / "docs-src" / "models" / "Model_Z",
            workspace / "dataset-700" / "base_run" / "deck",
        )
    )
    source_welspecs = _raw_keyword_block(source_raw, b"WELSPECS")
    source_dimens = _expand_integers(
        _keyword_payload((model_dir / _MODEL_DATA).read_bytes(), b"DIMENS"),
        "DIMENS",
    )
    source_pvtnum = _expand_integers(
        _keyword_payload(
            (model_dir / _REGIONS_INCLUDE).read_bytes().removeprefix(_UTF8_BOM),
            b"PVTNUM",
        ),
        "PVTNUM",
    )
    source_activation = _completion_activation_keys(source_parsed)
    source_other_fixed = _noncompletion_fixed_events(source_parsed)

    for candidate in candidates:
        candidate = candidate.resolve()
        schedule_file = candidate / _SCHEDULE_INCLUDE
        data_file = candidate / _MODEL_DATA
        regions_file = candidate / _REGIONS_INCLUDE
        if candidate == model_dir or not all(
            path.is_file() for path in (schedule_file, data_file, regions_file)
        ):
            continue
        candidate_raw = schedule_file.read_bytes().removeprefix(_UTF8_BOM)
        candidate_parsed = parse_schedule(candidate_raw)
        try:
            compatible = (
                _raw_keyword_block(candidate_raw, b"WELSPECS") == source_welspecs
                and _expand_integers(
                    _keyword_payload(data_file.read_bytes(), b"DIMENS"), "DIMENS"
                )
                == source_dimens
                and _expand_integers(
                    _keyword_payload(
                        regions_file.read_bytes().removeprefix(_UTF8_BOM), b"PVTNUM"
                    ),
                    "PVTNUM",
                )
                == source_pvtnum
            )
        except (OpmDeckError, SummaryPlanError):
            continue
        candidate_has_compdat = any(
            block.keyword == "COMPDAT" for block in candidate_parsed.blocks
        )
        candidate_has_md = any(
            block.keyword == "COMPDATMD" for block in candidate_parsed.blocks
        )
        candidate_has_tracks = (
            re.search(rb"(?m)^WELLTRACK(?:\s|$)", candidate_raw) is not None
        )
        if (
            compatible
            and candidate_has_compdat
            and not candidate_has_md
            and not candidate_has_tracks
            and candidate_parsed.dates == source_parsed.dates
            and _noncompletion_fixed_events(candidate_parsed) == source_other_fixed
            and _completion_activation_keys(candidate_parsed) == source_activation
        ):
            return candidate_parsed, candidate

    raise OpmDeckError(
        "WELLTRACK/COMPDATMD are not supported by Flow: no verified "
        "equivalent COMPDAT revision was found with matching WELSPECS, dates, "
        "fixed events, DIMENS and PVTNUM"
    )


def bundle_hash(files: Iterable[Path], root: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(files, key=lambda item: item.relative_to(root).as_posix()):
        name = path.relative_to(root).as_posix().encode("utf-8")
        content = path.read_bytes()
        digest.update(len(name).to_bytes(8, "big"))
        digest.update(name)
        digest.update(len(content).to_bytes(8, "big"))
        digest.update(content)
    return digest.hexdigest()
