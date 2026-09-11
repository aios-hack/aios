from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from backend.interfaces.cli.surrogate.tools.surrogate_metrics_errors import (
    FrozenHoldoutError,
    MetricsReportError,
)

HOLDOUT_FORMAT = "aios.surrogate-frozen-holdout.v1"
DEFAULT_HOLDOUT = Path("config/surrogate-holdout.json")


@dataclass(frozen=True, slots=True)
class FrozenHoldout:
    path: Path
    populated: bool
    hashes: frozenset[str]
    reason: str

    def as_provenance(self) -> dict[str, object]:
        return {
            "frozen_holdout": str(self.path),
            "frozen_holdout_populated": self.populated,
            "frozen_holdout_size": len(self.hashes),
            "frozen_holdout_note": self.reason,
        }


def load_frozen_holdout(path: Path = DEFAULT_HOLDOUT) -> FrozenHoldout:
    if not path.is_file():
        raise FrozenHoldoutError(
            f"there is no frozen holdout at {path}: without it neither the trainer "
            "nor the metrics report can prove the estimate was not obtained on a "
            "repeatedly reused sample"
        )
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise FrozenHoldoutError(
            f"the frozen holdout {path} is not readable: {error}"
        ) from error
    if not isinstance(payload, dict) or payload.get("format") != HOLDOUT_FORMAT:
        raise FrozenHoldoutError(
            f"unsupported frozen holdout format at {path}: "
            f"{payload.get('format') if isinstance(payload, dict) else type(payload).__name__!r}"
        )
    raw = payload.get("canonical_schedule_hashes")
    if not isinstance(raw, list):
        raise FrozenHoldoutError(
            f"{path}: canonical_schedule_hashes is not a list - there is nothing "
            "to exclude from training, and silently skipping would mean a leak"
        )
    hashes: set[str] = set()
    for item in raw:
        if not isinstance(item, str) or len(item) != 64:
            raise FrozenHoldoutError(
                f"{path}: entry {item!r} is not a canonical_schedule_hash"
            )
        hashes.add(item.lower())
    if len(hashes) != len(raw):
        raise FrozenHoldoutError(
            f"{path}: a canonical_schedule_hash is repeated, the set size cannot "
            "be computed from this list"
        )
    populated = bool(payload.get("populated", False))
    if populated != bool(hashes):
        raise FrozenHoldoutError(
            f"{path}: the field populated={populated} diverges from {len(hashes)} "
            "entries - the set must honestly declare whether it is populated"
        )
    if populated:
        reason = f"the set is frozen, {len(hashes)} schedules are excluded from training"
    else:
        raw_reason = payload.get("unpopulated_reason")
        if not isinstance(raw_reason, str) or not raw_reason.strip():
            raise FrozenHoldoutError(
                f"{path}: an unpopulated set must explain why it holds no schedule "
                "at all; an empty list without a reason is indistinguishable from a "
                "lost file"
            )
        reason = raw_reason.strip()
    return FrozenHoldout(
        path=path, populated=populated, hashes=frozenset(hashes), reason=reason
    )


def assert_holdout_excluded(
    holdout: FrozenHoldout, hashes: Sequence[str], population: str
) -> None:
    leaked = sorted({value.lower() for value in hashes} & holdout.hashes)
    if leaked:
        raise FrozenHoldoutError(
            f"{population}: {len(leaked)} schedules of the frozen holdout "
            f"{holdout.path} entered the sample - {', '.join(leaked[:3])}"
            f"{'...' if len(leaked) > 3 else ''}. Training or measuring on the "
            "frozen set destroys the only independent estimate, so this is an "
            "error, not a warning"
        )
