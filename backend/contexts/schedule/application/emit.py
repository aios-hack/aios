from __future__ import annotations

from backend.contexts.schedule.domain.errors import (
    ScheduleEmitError,
)

from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from backend.contexts.schedule.domain.schedule import ControlEvent, Schedule
from backend.shared.hashing import content_hash, hash_schedule

from backend.contexts.schedule.domain.build import ScheduleBuildError, build_schedule
from backend.contexts.schedule.domain.canonical import canonicalize
from backend.contexts.schedule.domain.lossless import (
    LosslessBlock,
    LosslessChunk,
    emit_lossless,
    ParsedSchedule,
    ScheduleParseError,
    parse_schedule,
)

WELLS_SCHEDULE_FILE_NAME: str = "well_schedule.inc"

_FUND_KEYWORDS: frozenset[str] = frozenset({"WCONPROD", "WCONINJE"})


@dataclass(frozen=True, slots=True)
class EmitStats:
    n_bytes: int
    n_dates: int
    n_wconprod_blocks: int
    n_wconinje_blocks: int
    n_compdat_blocks: int
    n_wpimult_blocks: int
    dropped_control_blocks: int

    @property
    def n_fund_blocks(self) -> int:
        return self.n_wconprod_blocks + self.n_wconinje_blocks

    @property
    def n_fixed_blocks(self) -> int:
        return self.n_compdat_blocks + self.n_wpimult_blocks


@dataclass(frozen=True, slots=True)
class EmittedSchedule:
    raw: bytes
    stats: EmitStats
    sparse: bool

    @property
    def content_hash(self) -> str:
        return content_hash(self.raw)

    def write(self, path: str | Path) -> Path:
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(self.raw)
        return target


def _block_stats(
    blocks: Sequence[LosslessBlock], n_dates: int, dropped: int
) -> EmitStats:
    counts: dict[str, int] = {}
    for block in blocks:
        counts[block.keyword] = counts.get(block.keyword, 0) + 1
    return EmitStats(
        n_bytes=0,
        n_dates=n_dates,
        n_wconprod_blocks=counts.get("WCONPROD", 0),
        n_wconinje_blocks=counts.get("WCONINJE", 0),
        n_compdat_blocks=counts.get("COMPDAT", 0) + counts.get("COMPDATMD", 0),
        n_wpimult_blocks=counts.get("WPIMULT", 0),
        dropped_control_blocks=dropped,
    )


def _is_redundant(previous: bytes | None, block: LosslessBlock) -> bool:
    if previous is None:
        return False
    if block.keyword not in _FUND_KEYWORDS:
        return False
    if block.fixed_deck_events:
        return False
    return _payload(previous) == _payload(block.raw)


def _payload(raw: bytes) -> tuple[bytes, ...]:
    return tuple(
        line.split(b"--", 1)[0].strip()
        for line in raw.splitlines()
        if line.split(b"--", 1)[0].strip()
    )


def emit_wells_schedule(
    parsed: ParsedSchedule, sparse: bool = False
) -> EmittedSchedule:
    if sparse:
        return _emit_sparse(parsed)
    raw = emit_lossless(parsed)
    stats = _block_stats(parsed.blocks, len(parsed.dates), 0)
    return EmittedSchedule(
        raw=raw,
        stats=EmitStats(
            n_bytes=len(raw),
            n_dates=stats.n_dates,
            n_wconprod_blocks=stats.n_wconprod_blocks,
            n_wconinje_blocks=stats.n_wconinje_blocks,
            n_compdat_blocks=stats.n_compdat_blocks,
            n_wpimult_blocks=stats.n_wpimult_blocks,
            dropped_control_blocks=0,
        ),
        sparse=False,
    )


def _emit_sparse(parsed: ParsedSchedule) -> EmittedSchedule:
    kept: list[LosslessChunk] = []
    kept_blocks: list[LosslessBlock] = []
    previous_by_keyword: dict[str, bytes] = {}
    dropped = 0
    for chunk in parsed.chunks:
        if isinstance(chunk, bytes):
            kept.append(chunk)
            continue
        if _is_redundant(previous_by_keyword.get(chunk.keyword), chunk):
            dropped += 1
            continue
        if chunk.keyword in _FUND_KEYWORDS:
            previous_by_keyword[chunk.keyword] = chunk.raw
        kept.append(chunk)
        kept_blocks.append(chunk)
    raw = b"".join(
        item if isinstance(item, bytes) else item.raw for item in kept
    )
    stats = _block_stats(kept_blocks, len(parsed.dates), dropped)
    return EmittedSchedule(
        raw=raw,
        stats=EmitStats(
            n_bytes=len(raw),
            n_dates=stats.n_dates,
            n_wconprod_blocks=stats.n_wconprod_blocks,
            n_wconinje_blocks=stats.n_wconinje_blocks,
            n_compdat_blocks=stats.n_compdat_blocks,
            n_wpimult_blocks=stats.n_wpimult_blocks,
            dropped_control_blocks=dropped,
        ),
        sparse=True,
    )


@dataclass(frozen=True, slots=True)
class RoundTripReport:
    byte_identical: bool
    source_hash: str
    emitted_hash: str
    n_source_bytes: int
    n_emitted_bytes: int
    first_difference: int | None
    control_events_match: bool
    fixed_events_match: bool
    dates_match: bool

    @property
    def ok(self) -> bool:
        return (
            self.byte_identical
            and self.control_events_match
            and self.fixed_events_match
            and self.dates_match
        )

    def format(self) -> str:
        if self.ok:
            return (
                f"round-trip byte for byte: {self.n_source_bytes} bytes, "
                f"content_hash {self.emitted_hash}"
            )
        return (
            f"round-trip did not match: bytes {self.n_source_bytes} against "
            f"{self.n_emitted_bytes}, first difference at position "
            f"{self.first_difference}, hashes {self.source_hash} against "
            f"{self.emitted_hash}, control events {self.control_events_match}, "
            f"fixed {self.fixed_events_match}, dates {self.dates_match}"
        )

    def raise_if_broken(self) -> None:
        if not self.ok:
            raise ScheduleEmitError(self.format())


def _first_difference(left: bytes, right: bytes) -> int | None:
    if left == right:
        return None
    for position, (a, b) in enumerate(zip(left, right)):
        if a != b:
            return position
    return min(len(left), len(right))


def round_trip(source: bytes) -> RoundTripReport:
    parsed = parse_schedule(source)
    emitted = emit_wells_schedule(parsed).raw
    try:
        reparsed = parse_schedule(emitted)
    except ScheduleParseError as error:
        raise ScheduleEmitError(
            f"the emitted file does not parse back: {error}"
        ) from error
    return RoundTripReport(
        byte_identical=emitted == source,
        source_hash=content_hash(source),
        emitted_hash=content_hash(emitted),
        n_source_bytes=len(source),
        n_emitted_bytes=len(emitted),
        first_difference=_first_difference(source, emitted),
        control_events_match=reparsed.control_events == parsed.control_events,
        fixed_events_match=reparsed.fixed_deck_events == parsed.fixed_deck_events,
        dates_match=reparsed.dates == parsed.dates,
    )


def emit_to_file(
    parsed: ParsedSchedule,
    directory: str | Path,
    sparse: bool = False,
    file_name: str = WELLS_SCHEDULE_FILE_NAME,
) -> tuple[Path, EmittedSchedule]:
    emitted = emit_wells_schedule(parsed, sparse=sparse)
    return emitted.write(Path(directory) / file_name), emitted


def emit_from_deck(
    source_path: str | Path,
    directory: str | Path,
    sparse: bool = False,
    file_name: str = WELLS_SCHEDULE_FILE_NAME,
) -> tuple[Path, EmittedSchedule, RoundTripReport]:
    source = Path(source_path).read_bytes()
    try:
        parsed = parse_schedule(source)
    except ScheduleParseError as error:
        raise ScheduleEmitError(
            f"deck {source_path!r} does not parse: {error}"
        ) from error
    report = round_trip(source)
    report.raise_if_broken()
    path, emitted = emit_to_file(parsed, directory, sparse=sparse, file_name=file_name)
    return path, emitted, report


@dataclass(frozen=True, slots=True)
class ScheduleDivergence:
    index: int
    expected: ControlEvent | None
    actual: ControlEvent | None

    def format(self) -> str:
        return (
            f"first divergence of the control layer at position "
            f"{self.index}: source {self.expected!r} against reparsed "
            f"{self.actual!r}"
        )


def _first_control_divergence(
    expected: Sequence[ControlEvent], actual: Sequence[ControlEvent]
) -> ScheduleDivergence | None:
    for index in range(max(len(expected), len(actual))):
        left = expected[index] if index < len(expected) else None
        right = actual[index] if index < len(actual) else None
        if left != right:
            return ScheduleDivergence(index=index, expected=left, actual=right)
    return None


@dataclass(frozen=True, slots=True)
class ScheduleRoundTripReport:
    source_hash: str
    reparsed_hash: str
    content_hash: str
    n_bytes: int
    divergence: ScheduleDivergence | None

    @property
    def ok(self) -> bool:
        return self.source_hash == self.reparsed_hash and self.divergence is None

    def format(self) -> str:
        if self.ok:
            return (
                f"schedule round-trip matched: {self.n_bytes} bytes, "
                f"content_hash {self.content_hash}, "
                f"canonical_schedule_hash {self.source_hash}"
            )
        detail = (
            self.divergence.format()
            if self.divergence is not None
            else "the control layer matched, the fixed layer or the initial "
            "state diverged"
        )
        return (
            f"schedule round-trip did not match: canonical_schedule_hash "
            f"{self.source_hash} against {self.reparsed_hash} over "
            f"{self.n_bytes} bytes (content_hash {self.content_hash}); "
            f"{detail}"
        )

    def raise_if_broken(self) -> None:
        if not self.ok:
            raise ScheduleEmitError(self.format())


def verify_schedule_round_trip(
    schedule: Schedule, raw: bytes, *, history_prefix: bytes = b""
) -> ScheduleRoundTripReport:
    submitted_raw = raw
    raw = history_prefix + raw
    try:
        parsed = parse_schedule(raw)
    except ScheduleParseError as error:
        raise ScheduleEmitError(
            f"the emitted schedule does not parse back: {error}"
        ) from error
    source = canonicalize(schedule)
    try:
        reparsed = canonicalize(
            build_schedule(
                parsed,
                raw,
                model=source.meta.model,
                provenance=source.meta.provenance,
            )
        )
    except ScheduleBuildError as error:
        raise ScheduleEmitError(
            f"the emitted schedule does not build into a Schedule: {error}"
        ) from error
    return ScheduleRoundTripReport(
        source_hash=hash_schedule(source),
        reparsed_hash=hash_schedule(reparsed),
        content_hash=content_hash(submitted_raw),
        n_bytes=len(submitted_raw),
        divergence=_first_control_divergence(
            source.control_events, reparsed.control_events
        ),
    )
