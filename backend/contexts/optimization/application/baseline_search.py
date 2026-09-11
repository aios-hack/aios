from __future__ import annotations

import logging

from backend.contexts.optimization.application.water_repair import (
    _repair_predicted_water_balance,
)
from backend.contexts.optimization.application.search_config import (
    SEARCH_DIAGNOSTICS,
)
from backend.contexts.optimization.infrastructure.diagnostics_journal import (
    candidate_card,
)
from backend.contexts.optimization.domain.injection_transfer import (
    _connectivity_groups,
    _injection_transfer_plan,
    _lambda_connectivity,
    _transfer_injection,
)
from backend.contexts.optimization.domain.selection import (
    SearchOutcome,
)
from backend.contexts.optimization.domain.gates.opm_budget import (
    close_run_clock,
)
from backend.contexts.optimization.domain.gates.incumbent import (
    IncumbentRegistry,
    _physics_admissible,
)
from backend.contexts.optimization.domain.gates.bhp_tolerance import (
    _bhp_tolerance_decision,
    surrogate_blocking_violations,
)
from backend.contexts.optimization.domain.errors import (
    SearchRunError,
)
import json
from typing import (
    Mapping,
)
from backend.contexts.schedule.domain.schedule import Schedule
from backend.contexts.policy.domain.policy import Theta
from backend.contexts.constraints.domain.constraints import compensation_policy
from backend.shared.hashing import hash_schedule
from backend.contexts.optimization.application.environment import (
    OutOfDomainScheduleError,
    PhysicallyImpossibleScheduleError,
)
from backend.contexts.policy.domain.theta import default_theta
from backend.contexts.schedule.domain.case_limits import YearlyProduction, apply_case_limits
from backend.contexts.schedule.domain.validate import validate_static
from backend.contexts.schedule.domain.validate_dynamic import (
    FIRST_CONTROL_DECK_DATE_INDEX,
    year_of_step,
)
from backend.shared.json_io import read_json

logger = logging.getLogger(__name__)


def _search_theta(constraints) -> Theta:
    base = default_theta()
    corridor = compensation_policy(constraints)
    if not corridor.enabled:
        return base
    assert corridor.minimum is not None and corridor.maximum is not None
    bounds = dict(base.bounds)
    low_floor, low_ceiling = bounds["r5_compensation_low"]
    high_floor, high_ceiling = bounds["r5_compensation_high"]
    bounds["r5_compensation_low"] = (
        max(low_floor, corridor.minimum),
        min(low_ceiling, corridor.maximum),
    )
    bounds["r5_compensation_high"] = (
        max(high_floor, corridor.minimum),
        min(high_ceiling, corridor.maximum),
    )
    for name in ("r5_compensation_low", "r5_compensation_high"):
        if bounds[name][0] >= bounds[name][1]:
            raise SearchRunError(
                f"the case corridor is incompatible with the bounds of {name}: {bounds[name]}"
            )
    values = dict(base.values)
    for name in ("r5_compensation_low", "r5_compensation_high"):
        values[name] = min(max(values[name], bounds[name][0]), bounds[name][1])
    return Theta(values=values, bounds=bounds)


def _peak_step_production(env, evaluator):
    def forecast(schedule: Schedule) -> YearlyProduction:
        response = evaluator(schedule).state.response
        liquid_by_step: dict[int, float] = {}
        injection_by_step: dict[int, float] = {}
        for state in response.state_at_date:
            control_step = state.deck_date_index - FIRST_CONTROL_DECK_DATE_INDEX - 1
            if control_step < 0:
                continue
            liquid_by_step[control_step] = (
                liquid_by_step.get(control_step, 0.0) + state.liquid_rate
            )
            injection_by_step[control_step] = (
                injection_by_step.get(control_step, 0.0) + state.injection_rate
            )
        liquid: dict[int, float] = {}
        injection: dict[int, float] = {}
        for control_step, value in liquid_by_step.items():
            year = year_of_step(schedule, control_step)
            liquid[year] = max(liquid.get(year, 0.0), value)
        for control_step, value in injection_by_step.items():
            year = year_of_step(schedule, control_step)
            injection[year] = max(injection.get(year, 0.0), value)
        return YearlyProduction(liquid_by_year=liquid, injection_by_year=injection)

    return forecast


def _search_near_baseline(
    env,
    evaluator,
    budget: int,
    provenance: dict[str, str],
    registry: "IncumbentRegistry | None" = None,
) -> SearchOutcome:
    registry = IncumbentRegistry() if registry is None else registry
    tolerance = _bhp_tolerance_decision()
    baseline = apply_case_limits(
        env.base_schedule,
        env.constraints,
        env.control_dates,
        _peak_step_production(env, evaluator),
    )
    strength = _lambda_connectivity(env.lambda_)
    groups = _connectivity_groups(strength)
    transfers = _injection_transfer_plan(env.lambda_, baseline, budget)
    candidates = [baseline]
    candidate_notes: list[str] = ["baseline"]
    for donor, receiver, volume in transfers:
        candidates.append(_transfer_injection(baseline, donor, receiver, volume))
        candidate_notes.append(
            f"{donor}({groups[donor]},{strength[donor]:.4f})"
            f"->{receiver}({groups[receiver]},{strength[receiver]:.4f})"
            f":{volume:.1f}"
        )
    scenario_ood_threshold = (
        float(env.scenario_ood.threshold) if env.scenario_ood is not None else None
    )
    records = []
    accepted = []
    for index, schedule in enumerate(candidates):
        violations = []
        npv = None
        npv_parts: Mapping[str, float] = {}
        physics: Mapping[str, int] = {}
        ood_score = None
        ood_worst = None
        ood_exceedances: tuple[dict[str, object], ...] = ()
        static_count = None
        blocking_count = None
        schedule_hash = hash_schedule(schedule)
        try:
            static = validate_static(schedule, env.constraints)
            static_count = len(static.violations)
            if not static.ok:
                violations.append({'scenario_id': 'static-contract', 'regret': len(static.violations),
                                   'what': f'Schedule condition violations: {len(static.violations)}'})
            else:
                schedule, evaluated, dynamic, _ = _repair_predicted_water_balance(env, evaluator, schedule)
                schedule_hash = hash_schedule(schedule)
                static = validate_static(schedule, env.constraints)
                blocking = surrogate_blocking_violations(
                    dynamic.blocking_violations, env.constraints, tolerance
                )
                static_count = len(static.violations)
                blocking_count = len(blocking)
                npv_parts = evaluated.npv_parts
                physics = evaluated.physics
                ood_score = evaluated.ood_score
                ood_worst = evaluated.ood_worst
                ood_exceedances = tuple(
                    getattr(evaluator, 'ood_exceedances', ()) or ()
                )
                admissible = _physics_admissible(physics)
                if not static.ok or blocking:
                    violations.append({'scenario_id': 'case-constraints', 'regret': len(blocking) + len(static.violations),
                                       'what': f'Constraint violations: {len(blocking) + len(static.violations)}'})
                elif not admissible:
                    violations.append({'scenario_id': 'surrogate-physics', 'regret': 1,
                                       'what': 'The physics check did not pass or is incomplete.'})
                elif ood_score is None or (
                    not env.ood_soft_penalty and ood_score > env.ood_threshold
                ):
                    violations.append({'scenario_id': 'surrogate-domain', 'regret': 1,
                                       'what': 'The schedule is outside the training domain.'})
                else:
                    npv = evaluated.npv
                    accepted.append((npv, schedule, index, static_count, blocking_count))
                    best = registry.current
                    if best is None or npv > best.npv_predicted:
                        registry.promote(
                            stage='lambda-connectivity-transfer',
                            schedule_hash=schedule_hash,
                            npv_predicted=npv,
                            theta={},
                            ood_score=ood_score,
                            ood_worst=ood_worst,
                            static_violations=static_count,
                            dynamic_blocking_violations=blocking_count,
                            physics_admissible=admissible,
                            self_consistent=False,
                            ood_exceedances=ood_exceedances,
                        )
        except (OutOfDomainScheduleError, PhysicallyImpossibleScheduleError) as error:
            ood_score = getattr(error, 'score', None)
            physics = getattr(error, 'counts', {}) or {}
            ood_exceedances = tuple(getattr(error, 'exceedances', ()) or ())
            violations.append({'scenario_id': 'surrogate-rejected', 'regret': 1, 'what': str(error)})
        records.append(
            candidate_card(
                schedule_hash=schedule_hash,
                theta={},
                npv_predicted=npv,
                npv_parts=npv_parts,
                ood_score=ood_score,
                ood_worst=ood_worst,
                scenario_ood=scenario_ood_threshold,
                physics=physics,
                static_violations=static_count,
                dynamic_blocking_violations=blocking_count,
                feasible=not violations,
                violations=violations,
                strategy='lambda-connectivity-transfer',
                ood_exceedances=ood_exceedances,
            )
        )
        logger.info(f'local variant {index + 1}/{budget}: feasible={not violations}, NPV={npv}')
    diagnostics = read_json(SEARCH_DIAGNOSTICS)
    diagnostics['fallback_budget'] = budget
    diagnostics['evaluations'].extend(records)
    diagnostics['incumbents'] = registry.as_list()
    SEARCH_DIAGNOSTICS.write_text(
        json.dumps(diagnostics, ensure_ascii=False, indent=2, allow_nan=False),
        encoding='utf-8',
    )
    if not accepted:
        raise SearchRunError('Neither the policy nor local modifications of the source schedule passed the condition and training-domain checks.')
    npv, schedule, index, static_count, blocking_count = max(accepted, key=lambda item: item[0])
    provenance = dict(provenance, search_strategy='lambda-connectivity-transfer',
                      selected_candidate=candidate_notes[index],
                      candidate_generator='injection transferred from low-lambda '
                                          'to high-lambda injectors, ranked by '
                                          'column connectivity',
                      candidate_groups=','.join(
                          sorted({groups[donor] + '->' + groups[receiver]
                                  for donor, receiver, _ in transfers})),
                      policy_equilibrium='not-claimed',
                      **tolerance.as_provenance())
    run_budget = close_run_clock(len(diagnostics['evaluations']))
    provenance = dict(provenance, **run_budget.as_provenance())
    return SearchOutcome(schedule, default_theta(), npv, hash_schedule(schedule), provenance,
                         len(diagnostics['evaluations']), False, False,
                         static_count, blocking_count, registry.records, run_budget)
