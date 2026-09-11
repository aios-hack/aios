from __future__ import annotations

import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from backend.contexts.constraints.infrastructure.constraints_io import (
    YEAR_SECTIONS,
    constraints_from_json,
    constraints_to_json,
)
from backend.contexts.constraints.domain.constraints import Constraints

from backend.contexts.showcase.infrastructure.artifact_io import load_bundle
from backend.contexts.showcase.application.exporters.physics_view import (
    PHYSICS_INVARIANTS,
    PHYSICS_TOTAL,
    ScenarioPhysics,
    physics_json,
)

__all__ = [
    "YEAR_SECTIONS",
    "REGRET_PARTS",
    "PHYSICS_INVARIANTS",
    "PHYSICS_TOTAL",
    "WorstRegret",
    "ScenarioPhysics",
    "ScenarioRobustness",
    "constraints_to_json",
    "constraints_from_json",
    "build_scenario_index",
    "export_scenarios_json",
]

REGRET_PARTS: tuple[str, ...] = ("optimization", "holdout")


@dataclass(frozen=True, slots=True)
class WorstRegret:
    scenario_id: str
    value_rub: float
    part: str

    def __post_init__(self) -> None:
        if self.part not in REGRET_PARTS:
            raise ValueError(
                f"unknown battery part {self.part!r}: expected one of "
                f"{', '.join(REGRET_PARTS)}"
            )
        if not self.scenario_id:
            raise ValueError("worst-regret scenario has no identifier")


@dataclass(frozen=True, slots=True)
class ScenarioRobustness:
    ood_score: float | None = None
    ood_threshold: float | None = None
    worst_regret: WorstRegret | None = None
    final_npv_rub: float | None = None
    final_npv_run_id: str | None = None
    predicted_npv_rub: float | None = None
    calibrated_npv_rub: float | None = None
    run_validation_clean: bool | None = None
    physics: ScenarioPhysics | None = None

    def __post_init__(self) -> None:
        if (self.final_npv_rub is None) != (self.final_npv_run_id is None):
            raise ValueError(
                "final_npv is the claimed number together with the run that produced "
                "it: half of the pair is not allowed"
            )
        if self.ood_score is not None and self.ood_threshold is None:
            raise ValueError(
                "ood_score without ood_threshold is unreadable: the threshold defines "
                "what out-of-domain means"
            )
        if self.predicted_npv_rub is not None and not math.isfinite(
            self.predicted_npv_rub
        ):
            raise ValueError("predicted_npv_rub must be a finite number")
        if self.calibrated_npv_rub is not None and not math.isfinite(
            self.calibrated_npv_rub
        ):
            raise ValueError("calibrated_npv_rub must be a finite number")
        if self.run_validation_clean is not None and not isinstance(
            self.run_validation_clean, bool
        ):
            raise ValueError("run_validation_clean must be a bool or null")


def _robustness_json(robustness: ScenarioRobustness) -> dict[str, Any]:
    regret = robustness.worst_regret
    final_npv = (
        None
        if robustness.final_npv_rub is None
        else {
            "npv_rub": robustness.final_npv_rub,
            "run_id": robustness.final_npv_run_id,
        }
    )
    return {
        "ood_score": robustness.ood_score,
        "ood_threshold": robustness.ood_threshold,
        "worst_regret": (
            None
            if regret is None
            else {
                "scenario_id": regret.scenario_id,
                "value_rub": regret.value_rub,
                "part": regret.part,
            }
        ),
        "final_npv": final_npv,
        "predicted_npv_rub": robustness.predicted_npv_rub,
        "calibrated_npv_rub": robustness.calibrated_npv_rub,
        "run_validation_clean": robustness.run_validation_clean,
        "physics": physics_json(robustness.physics),
    }


def _constraints_summary(c: Constraints) -> dict[str, Any]:
    years: set[int] = set()
    for section in YEAR_SECTIONS:
        years.update(getattr(c, section))
    return {
        "injection_limits": len(c.injection_limits),
        "liquid_limits": len(c.liquid_limits),
        "production_floors": len(c.production_floors),
        "watercut_limits": len(c.watercut_limits),
        "well_outages": len(c.well_outages),
        "infrastructure": len(c.infrastructure),
        "years": sorted(years),
        "outage_wells": sorted({o.well for o in c.well_outages}),
        "empty": not (years or c.well_outages or c.infrastructure),
    }


def build_scenario_index(
    artifact_paths: list[Path],
    robustness: dict[str, ScenarioRobustness] | None = None,
) -> dict[str, Any]:
    robustness = robustness or {}
    scenarios: list[dict[str, Any]] = []
    submitted: list[str] = []
    for path in artifact_paths:
        artifact = load_bundle(path)
        scenario_id = Path(path).stem
        measured = robustness.get(scenario_id, ScenarioRobustness())
        is_submitted = artifact.final_npv is not None
        if is_submitted:
            submitted.append(scenario_id)
        artifact_npv = (
            artifact.final_npv.npv_methodology
            if artifact.final_npv is not None
            else None
        )
        scenarios.append(
            {
                "id": scenario_id,
                "config_hash": artifact.config_hash,
                "converged": artifact.converged,
                "self_consistent": artifact.self_consistent,
                "is_submitted": is_submitted,
                "npv_methodology": (
                    artifact_npv
                    if artifact_npv is not None
                    else measured.final_npv_rub
                ),
                "constraints": _constraints_summary(artifact.constraints),
                **_robustness_json(measured),
            }
        )
    if len(submitted) > 1:
        raise ValueError(
            "final_npv is filled in for more than one scenario "
            f"({', '.join(sorted(submitted))}): exactly one may be submitted"
        )
    return {"scenarios": scenarios, "submitted": submitted[0] if submitted else None}


def export_scenarios_json(
    artifact_paths: list[Path],
    out_path: str | Path,
    robustness: dict[str, ScenarioRobustness] | None = None,
) -> Path:
    index = build_scenario_index(artifact_paths, robustness)
    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(index, ensure_ascii=False, indent=2), encoding="utf-8")
    return out
