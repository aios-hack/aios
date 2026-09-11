from __future__ import annotations

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


def _write_diagnostics_tail(
    finalist_cards: Sequence[Mapping[str, object]],
    registry: "IncumbentRegistry",
) -> None:
    if not SEARCH_DIAGNOSTICS.is_file():
        raise SearchRunError(
            f"диагностика поиска {SEARCH_DIAGNOSTICS} не записана: "
            "дописывать финалистов и реестр incumbent некуда"
        )
    diagnostics = read_json(SEARCH_DIAGNOSTICS)
    diagnostics["finalists"] = [dict(card) for card in finalist_cards]
    diagnostics["incumbents"] = registry.as_list()
    SEARCH_DIAGNOSTICS.write_text(
        json.dumps(diagnostics, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )


def _evaluation_cards(
    history: Sequence[object], cards: Sequence[Mapping[str, object]]
) -> list[dict[str, object]]:
    if len(cards) != len(history):
        raise SearchRunError(
            f"диагностика кандидатов рассинхронизирована с историей поиска: "
            f"карточек {len(cards)}, оценок {len(history)} — сводить нечего"
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
