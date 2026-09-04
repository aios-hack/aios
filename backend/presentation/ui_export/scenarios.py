from __future__ import annotations

import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from backend.application.cases import YEAR_SECTIONS, constraints_from_json
from backend.core.contracts import Constraints

from backend.presentation.ui_export.artifact_io import load_bundle

__all__ = [
    "YEAR_SECTIONS",
    "REGRET_PARTS",
    "WorstRegret",
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
                f"часть батареи «{self.part}» неизвестна: ожидается одна из "
                f"{', '.join(REGRET_PARTS)}"
            )
        if not self.scenario_id:
            raise ValueError("худший сожалению сценарий без идентификатора")


@dataclass(frozen=True, slots=True)
class ScenarioRobustness:
    """Показатели F8 по одному сценарию. `None` — «не измерено», и это не
    то же самое, что измеренный ноль: интерфейс их различает."""

    ood_score: float | None = None
    ood_threshold: float | None = None
    worst_regret: WorstRegret | None = None
    final_npv_rub: float | None = None
    final_npv_run_id: str | None = None
    predicted_npv_rub: float | None = None
    calibrated_npv_rub: float | None = None
    run_validation_clean: bool | None = None

    def __post_init__(self) -> None:
        if (self.final_npv_rub is None) != (self.final_npv_run_id is None):
            raise ValueError(
                "final_npv — заявленное число вместе с прогоном, который его дал: "
                "половина пары запрещена"
            )
        if self.ood_score is not None and self.ood_threshold is None:
            raise ValueError(
                "ood_score без ood_threshold нечитаем: порог задаёт, что значит «вне области»"
            )
        if self.predicted_npv_rub is not None and not math.isfinite(
            self.predicted_npv_rub
        ):
            raise ValueError("predicted_npv_rub должен быть конечным числом")
        if self.calibrated_npv_rub is not None and not math.isfinite(
            self.calibrated_npv_rub
        ):
            raise ValueError("calibrated_npv_rub должен быть конечным числом")
        if self.run_validation_clean is not None and not isinstance(
            self.run_validation_clean, bool
        ):
            raise ValueError("run_validation_clean должен быть bool или null")


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
    }


def constraints_to_json(c: Constraints) -> dict[str, Any]:
    return {
        "injection_limits": {str(y): float(v) for y, v in sorted(c.injection_limits.items())},
        "liquid_limits": {str(y): float(v) for y, v in sorted(c.liquid_limits.items())},
        "production_floors": {str(y): float(v) for y, v in sorted(c.production_floors.items())},
        "watercut_limits": {str(y): float(v) for y, v in sorted(c.watercut_limits.items())},
        "well_outages": [
            {
                "well": o.well,
                "control_step_from": o.control_step_from,
                "control_step_to": o.control_step_to,
            }
            for o in c.well_outages
        ],
        "infrastructure": dict(c.infrastructure),
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
    """`robustness` — показатели F8 по идентификатору сценария. Сценарий, о
    котором ничего не измерено, получает `null` во всех четырёх полях: их
    отсутствие в записи и измеренный ноль — разные утверждения."""

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
                # Подтверждённый полный прогон не обязан быть сдаваемым
                # сценарием. Base измерен OPM, но is_submitted остаётся false.
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
            "final_npv заполнен более чем у одного сценария "
            f"({', '.join(sorted(submitted))}): сдан может быть ровно один"
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
