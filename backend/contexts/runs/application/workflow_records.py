from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from backend.contexts.constraints.domain.constraints import Constraints
from backend.contexts.constraints.infrastructure.constraints_io import constraints_hash
from backend.contexts.runs.domain.errors import SubmissionError
from backend.contexts.runs.domain.run_result import SubmissionBundle
from backend.contexts.runs.application.workflow_models import (
    MANIFEST_PROVENANCE_FIELDS,
    SUBMISSION_BUNDLE_FIELDS,
    RunProvenance,
)


def _provenance_fields(
    provenance: RunProvenance, constraints: Constraints | None = None
) -> dict[str, object]:
    fields = {name: getattr(provenance, name) for name in MANIFEST_PROVENANCE_FIELDS}
    if constraints is not None:
        fields["constraints_hash"] = constraints_hash(constraints)
    return fields


def _constraints_report(
    dynamic_report: object, constraints_hash_value: object
) -> dict[str, object]:
    checks = getattr(dynamic_report, "constraint_checks", ())
    if dynamic_report is None or not checks:
        reason = (
            "there is no dynamic report: OPM never reached response parsing, "
            "so not a single case constraint was checked"
            if dynamic_report is None
            else "the dynamic report was built without records of the applied "
            "constraints: the set of checks is unknown"
        )
        return {
            "constraints_hash": constraints_hash_value,
            "checks": None,
            "unavailable_reason": (
                f"{reason}; an empty list of checks here would read as "
                "\"there are no constraints\", and that is not the case"
            ),
        }
    return {
        "constraints_hash": constraints_hash_value,
        "checks": [item.as_dict() for item in checks],
        "unavailable_reason": None,
    }


def _required_text(value: object, name: str, run_id: str) -> str:
    if isinstance(value, str) and value.strip():
        return value
    raise SubmissionError(
        f"the submission bundle cannot be built: run {run_id!r} has no {name}, "
        f"got {value!r}; substituting a plausible value is forbidden"
    )


def _bundle_to_json(bundle: SubmissionBundle) -> dict[str, object]:
    return {name: getattr(bundle, name) for name in SUBMISSION_BUNDLE_FIELDS}


def _created_at(existing: Path) -> str:
    if existing.is_file():
        try:
            recorded = json.loads(existing.read_text(encoding="utf-8"))
        except ValueError:
            recorded = None
        if isinstance(recorded, dict):
            stamp = recorded.get("created_at")
            if isinstance(stamp, str) and stamp.strip():
                return stamp
    return datetime.now(timezone.utc).isoformat(timespec="seconds")
