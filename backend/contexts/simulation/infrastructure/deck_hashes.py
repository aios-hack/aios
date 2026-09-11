from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

from backend.contexts.simulation.domain.errors import OpmRunnerError
from backend.contexts.runs.domain.run_result import SummarySpec
from backend.contexts.schedule.domain.schedule import Schedule
from backend.shared.hashing import canonical_bytes, hash_schedule
from backend.contexts.reservoir.infrastructure.opm_deck import EmittedOpmDeck, bundle_hash

_NOT_CONVERGED_MARKERS: tuple[str, ...] = (
    "Solver failed to converge",
)

_ITERATION_LIMIT_MARKER = "Solver convergence failure"
_CHOP_RECOVERY_MARKER = "Timestep chopped to"
_CHOP_RECOVERY_LOOKAHEAD_LINES = 5

_RECOVERABLE_MARKERS: tuple[str, ...] = (
    "Linear solver convergence failure",
    "Convergence failure for linear solver",
    "Unconverged local solution with well convergence failures",
)

@dataclass(frozen=True, slots=True)
class DeckHashes:
    deck_hash: str
    canonical_schedule_hash: str
    summary_hash: str


def summary_spec_hash(spec: SummarySpec) -> str:
    return hashlib.sha256(canonical_bytes(spec)).hexdigest()


def static_deck_hash(deck: EmittedOpmDeck) -> str:
    variable = {deck.schedule_file.resolve(), deck.summary_file.resolve()}
    static = [path for path in deck.input_files if path.resolve() not in variable]
    if len(static) != len(deck.input_files) - len(variable):
        raise OpmRunnerError(
            "the deck input_files do not contain exactly two variable files "
            f"({deck.schedule_file.name}, {deck.summary_file.name})"
        )
    return bundle_hash(static, deck.data_file.parent)


def deck_hashes(deck: EmittedOpmDeck, schedule: Schedule) -> DeckHashes:
    return DeckHashes(
        deck_hash=static_deck_hash(deck),
        canonical_schedule_hash=hash_schedule(schedule),
        summary_hash=summary_spec_hash(deck.summary_plan.spec),
    )


def _tail(path: Path, *, max_lines: int = 15, max_chars: int = 2000) -> str:
    try:
        lines = [
            line.rstrip()
            for line in path.read_text(encoding="utf-8", errors="replace").splitlines()
            if line.strip()
        ]
    except OSError as error:
        return f"<log was not read: {error}>"
    text = "\n".join(lines[-max_lines:])
    return text[-max_chars:]


def _unrecovered_iteration_limit_failure(path: Path) -> bool:
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return False
    for index, line in enumerate(lines):
        if _ITERATION_LIMIT_MARKER not in line:
            continue
        window = lines[index : index + 1 + _CHOP_RECOVERY_LOOKAHEAD_LINES]
        if not any(_CHOP_RECOVERY_MARKER in window_line for window_line in window):
            return True
    return False


def _first_marker(path: Path, markers: Sequence[str]) -> str | None:
    try:
        with path.open("r", encoding="utf-8", errors="replace") as log:
            for line in log:
                for marker in markers:
                    if marker in line:
                        return marker
    except OSError:
        return None
    return None

