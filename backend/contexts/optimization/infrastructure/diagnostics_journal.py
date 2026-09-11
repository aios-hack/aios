from __future__ import annotations

from pathlib import Path

from backend.contexts.optimization.application.search_config import (
    SEARCH_DIAGNOSTICS,
)

from backend.contexts.optimization.domain.errors import (
    SearchRunError,
)
import json
import math
from typing import Mapping, Sequence
from backend.shared.json_io import read_json


def candidate_card(
    *,
    schedule_hash: str,
    theta: Mapping[str, float],
    npv_predicted: float | None,
    npv_parts: Mapping[str, float],
    ood_score: float | None,
    ood_worst: str | None,
    scenario_ood: float | None,
    physics: Mapping[str, int],
    static_violations: int | None,
    dynamic_blocking_violations: int | None,
    feasible: bool,
    violations: Sequence[Mapping[str, object]],
    strategy: str,
    ood_exceedances: Sequence[Mapping[str, object]] = (),
) -> dict[str, object]:
    counts = {name: int(value) for name, value in sorted(physics.items())}
    return {
        "strategy": strategy,
        "schedule_hash": schedule_hash,
        "theta": {name: float(value) for name, value in theta.items()},
        "npv_predicted": npv_predicted,
        "npv_parts": {
            name: float(value) for name, value in sorted(npv_parts.items())
        },
        "ood_score": ood_score,
        "ood_worst": ood_worst,
        "ood_exceedances": [dict(item) for item in ood_exceedances],
        "scenario_ood": scenario_ood,
        "physics_counts": counts,
        "physics_complete": bool(counts.get("complete", 0)),
        "physics_admissible": bool(counts.get("admissible", 0)),
        "static_violations": static_violations,
        "dynamic_blocking_violations": dynamic_blocking_violations,
        "feasible": feasible,
        "violations": [dict(item) for item in violations],
    }


def _write_diagnostics_head(
    *,
    seed: int,
    budget: int,
    search_cap: int,
    final_cap: int,
    env: object,
    threshold_decision: object,
    soft_penalty: bool,
    penalty_rate: float,
    bhp_tolerance: object,
    history: Sequence[object],
    cards: Sequence[Mapping[str, object]],
    registry: "IncumbentRegistry",
    path: Path | None = None,
) -> None:
    journal = SEARCH_DIAGNOSTICS if path is None else path
    journal.parent.mkdir(parents=True, exist_ok=True)
    journal.write_text(
        json.dumps(
            {
                "seed": seed,
                "budget": budget,
                "search_cap": search_cap,
                "final_cap": final_cap,
                "model_version": env.model.version,
                "npv_head_version": env.npv_head.version if env.npv_head else None,
                "ood_threshold": env.ood_threshold,
                "ood_threshold_origin": threshold_decision.origin,
                "ood_threshold_calibrated": threshold_decision.calibrated,
                "ood_soft_penalty": soft_penalty,
                "ood_penalty_per_unit": penalty_rate,
                "bhp_gate_delta_bar": bhp_tolerance.delta_bar,
                "bhp_gate_delta_origin": bhp_tolerance.origin,
                "bhp_gate_delta_detail": bhp_tolerance.detail,
                "evaluations": _evaluation_cards(history, cards),
                "incumbents": registry.as_list(),
            },
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        ),
        encoding="utf-8",
    )


def _write_diagnostics_tail(
    finalist_cards: Sequence[Mapping[str, object]],
    registry: "IncumbentRegistry",
    path: Path | None = None,
) -> None:
    journal = SEARCH_DIAGNOSTICS if path is None else path
    if not journal.is_file():
        raise SearchRunError(
            f"search diagnostics {journal} were not written: there is nowhere to "
            "append the finalists and the incumbent registry"
        )
    diagnostics = read_json(journal)
    diagnostics["finalists"] = [dict(card) for card in finalist_cards]
    diagnostics["incumbents"] = registry.as_list()
    journal.write_text(
        json.dumps(diagnostics, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )


def _evaluation_cards(
    history: Sequence[object], cards: Sequence[Mapping[str, object]]
) -> list[dict[str, object]]:
    if len(cards) != len(history):
        raise SearchRunError(
            f"candidate diagnostics are out of sync with the search history: "
            f"{len(cards)} cards, {len(history)} evaluations — there is nothing to reconcile"
        )
    merged: list[dict[str, object]] = []
    for item, card in zip(history, cards):
        objective = float(item.result.objective)
        entry = dict(card)
        entry["theta"] = dict(item.theta.values)
        entry["npv_predicted"] = objective if math.isfinite(objective) else None
        entry["feasible"] = item.result.feasible
        entry["violations"] = [
            {
                "scenario_id": violation.scenario_id,
                "regret": violation.regret,
                "what": violation.what,
            }
            for violation in item.result.violations_by_scenario
        ]
        merged.append(entry)
    return merged


__all__ = [
    "candidate_card",
]
