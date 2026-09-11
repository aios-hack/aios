from __future__ import annotations

import json
from pathlib import Path

from backend.contexts.economics.application.base_case import save_response_artifact
from backend.contexts.schedule.domain.schedule import Schedule
from backend.contexts.simulation.application.submission import SubmissionResult
from backend.shared.hashing import canonical_bytes, hash_schedule

from backend.contexts.optimization.application.verification_guard import GuardReport


def persist_observation(
    schedule: Schedule,
    result: SubmissionResult,
    *,
    predicted_npv: float | None,
    observation_root: Path = Path("data/opm-observations"),
    metadata: dict[str, object] | None = None,
    guard: GuardReport | None = None,
) -> Path:
    schedule_hash = hash_schedule(schedule)
    observation_dir = observation_root / schedule_hash
    observation_dir.mkdir(parents=True, exist_ok=True)
    (observation_dir / "schedule.json").write_bytes(canonical_bytes(schedule))
    if result.response is not None:
        save_response_artifact(result.response, observation_dir / "response.json")
    if result.dynamic_report is not None:
        (observation_dir / "dynamic-report.json").write_bytes(
            canonical_bytes(result.dynamic_report)
        )
    final_summary = None
    if result.final_npv is not None:
        final_summary = {
            "npv_methodology": result.final_npv.npv_methodology,
            "source_run_id": result.final_npv.source_run_id,
            "source_response_hash": result.final_npv.source_response_hash,
            "economics_config_hash": result.final_npv.economics_config_hash,
            "methodology_version_hash": result.final_npv.methodology_version_hash,
        }
        (observation_dir / "final-npv-summary.json").write_text(
            json.dumps(final_summary, ensure_ascii=False, indent=2, sort_keys=True),
            encoding="utf-8",
        )
    (observation_dir / "observation.json").write_text(
        json.dumps(
            {
                "canonical_schedule_hash": schedule_hash,
                "run_id": result.opm_run.run_id,
                "run_status": str(result.opm_run.status),
                "sound": result.sound,
                "predicted_npv": predicted_npv,
                "opm_npv": final_summary["npv_methodology"] if final_summary else None,
                "dynamic_violations": (
                    len(result.dynamic_report.violations)
                    if result.dynamic_report is not None
                    else None
                ),
                "verification_guard": guard.as_dict() if guard is not None else None,
                "metadata": metadata or {},
            },
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    return observation_dir
