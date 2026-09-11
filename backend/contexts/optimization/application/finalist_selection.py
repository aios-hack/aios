from __future__ import annotations

import logging
from typing import Any, Callable, Sequence

from backend.contexts.optimization.application.environment import (
    OutOfDomainScheduleError,
    PhysicallyImpossibleScheduleError,
)
from backend.contexts.optimization.application.policy_factory import make_policy
from backend.contexts.optimization.application.water_repair import (
    _repair_predicted_water_balance,
)
from backend.contexts.optimization.domain.gates.bhp_tolerance import (
    surrogate_blocking_violations,
)
from backend.contexts.optimization.domain.gates.incumbent import (
    FINALIST_CAP,
    IncumbentRegistry,
    _physics_admissible,
    incumbent_gate_passed,
)
from backend.contexts.optimization.infrastructure.diagnostics_journal import candidate_card
from backend.contexts.policy.domain.fixed_point import resolve
from backend.contexts.schedule.domain.validate import validate_static
from backend.shared.hashing import hash_schedule

logger = logging.getLogger(__name__)


def evaluate_finalists(
    ranked: Sequence[Any],
    *,
    env: Any,
    evaluator: Callable[..., Any],
    final_evaluator: Callable[..., Any],
    initial: Any,
    final_cap: int,
    bhp_tolerance: Any,
    soft_penalty: bool,
    scenario_ood_threshold: Any,
    registry: IncumbentRegistry,
) -> tuple[list[tuple[Any, ...]], list[dict[str, object]]]:
    finalists: list[tuple[Any, ...]] = []
    finalist_cards: list[dict[str, object]] = []
    seen: set[tuple[tuple[str, float], ...]] = set()
    logger.info("\nfull recomputation of the best feasible θ:")
    for candidate in ranked:
        signature = tuple(sorted(candidate.theta.values.items()))
        if signature in seen:
            continue
        seen.add(signature)
        try:
            final = resolve(
                make_policy(env, candidate.theta, {}), evaluator, initial, final_cap
            )
            check = validate_static(final.schedule, env.constraints)
            repaired_schedule, evaluated, dynamic, repair_rounds = _repair_predicted_water_balance(
                env, final_evaluator, final.schedule
            )
            check = validate_static(repaired_schedule, env.constraints)
        except (OutOfDomainScheduleError, PhysicallyImpossibleScheduleError) as error:
            logger.info(f"  finalist rejected: {error}")
            continue
        surrogate_blocking = surrogate_blocking_violations(
            dynamic.blocking_violations, env.constraints, bhp_tolerance
        )
        repaired_hash = hash_schedule(repaired_schedule)
        finalist_exceedances = tuple(
            getattr(final_evaluator, "ood_exceedances", ()) or ()
        )
        admissible = _physics_admissible(evaluated.physics)
        passed = incumbent_gate_passed(
            static_violations=len(check.violations),
            dynamic_blocking_violations=len(surrogate_blocking),
            ood_score=evaluated.ood_score,
            ood_threshold=env.ood_threshold,
            physics_admissible=admissible,
            ood_soft_penalty=soft_penalty,
        )
        finalist_cards.append(
            candidate_card(
                schedule_hash=repaired_hash,
                theta=dict(candidate.theta.values),
                npv_predicted=evaluated.npv,
                npv_parts=evaluated.npv_parts,
                ood_score=evaluated.ood_score,
                ood_worst=evaluated.ood_worst,
                scenario_ood=scenario_ood_threshold,
                physics=evaluated.physics,
                static_violations=len(check.violations),
                dynamic_blocking_violations=len(surrogate_blocking),
                feasible=passed,
                violations=[],
                strategy="finalist",
                ood_exceedances=finalist_exceedances,
            )
        )
        logger.info(
            f"  NPV {final.npv / 1e9:8.3f} bln, iterations {final.iterations:2d}, "
            f"self-consistent={final.self_consistent}, OOD={evaluated.ood_score}, "
            f"water-repair={repair_rounds}, static={len(check.violations)}, "
            f"dynamic-blocking={len(surrogate_blocking)}, "
            f"physics-admissible={admissible}, "
            f"BHP-to-OPM={len(dynamic.blocking_violations) - len(surrogate_blocking)}",
        )
        if passed:
            finalists.append(
                (
                    evaluated.npv,
                    candidate.theta,
                    repaired_schedule,
                    final,
                    check,
                    surrogate_blocking,
                    repaired_hash,
                    evaluated.sigma,
                )
            )
            best = registry.current
            if best is None or evaluated.npv > best.npv_predicted:
                registry.promote(
                    stage="finalist",
                    schedule_hash=repaired_hash,
                    npv_predicted=evaluated.npv,
                    theta=dict(candidate.theta.values),
                    ood_score=evaluated.ood_score,
                    ood_worst=evaluated.ood_worst,
                    static_violations=len(check.violations),
                    dynamic_blocking_violations=len(surrogate_blocking),
                    physics_admissible=admissible,
                    self_consistent=final.self_consistent,
                    ood_exceedances=finalist_exceedances,
                )
        if len(seen) >= FINALIST_CAP:
            break
    return finalists, finalist_cards
