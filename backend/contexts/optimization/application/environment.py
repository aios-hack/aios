from __future__ import annotations

from backend.contexts.optimization.application.ensemble_spread import (
    ensemble_members,
    spread_bracket,
)
from backend.contexts.optimization.application.policy_factory import (
    _flow_start_steps,
    _outage_events,
)
from backend.contexts.optimization.domain.errors import (
    EnsembleSpreadError,
    LambdaDesyncError,
    OutOfDomainScheduleError,
    PhysicallyImpossibleScheduleError,
    SELF_REFERENCE_SKIP_REASON,
)
from backend.contexts.optimization.domain.injection_budget import (
    _field_limit_for_step,
    _scale_step_injection_to_limit,
)
from backend.contexts.optimization.domain.ood_penalty import (
    OOD_EXCEEDANCE_LIMIT,
    exceedance_record,
    ood_penalty_factor,
)

from backend.contexts.optimization.application.economics_prediction import (
    predict_economics,
)

from backend.contexts.optimization.domain.search_environment import (
    SearchEnvironment,
)

from backend.contexts.optimization.application.policy_factory import (
    PolicyFeedback,
)

from backend.contexts.optimization.application.ensemble_spread import (
    ensemble_npv_sigma,
)

from backend.contexts.optimization.domain.physics_gate import (
    _enforce_physics,
    full_physics_report,
    physics_counters,
)

from backend.contexts.optimization.domain.ood_penalty import (
    _enforce_ood_threshold,
    _enforce_scenario_ood,
    _ood_threshold_excess,
    _scenario_ood_excess,
    apply_ood_penalty,
    format_ood_exceedances,
    format_ood_worst,
)

from backend.contexts.optimization.domain.provenance import (
    _lambda_strict_enabled,
    _validate_npv_head_compatibility,
    _validate_npv_scoring_is_unambiguous,
    lambda_sync_provenance,
    npv_blend_provenance,
)


from backend.contexts.optimization.domain.errors import (
    ScheduleSearchError,
)

from backend.contexts.surrogate.domain.npv_block_head import (
    load_direct_npv_head,
)
from backend.contexts.robustness.domain.scenario_ood import ScenarioDensityDomain
from backend.contexts.surrogate.domain.npv_calibration import NpvCalibration
from backend.contexts.surrogate.domain.raw_model_output import RawModelOutput


import hashlib
from dataclasses import (
    replace,
)
from pathlib import Path
from types import MappingProxyType

from backend.contexts.constraints.domain.schema import default_policies
from backend.contexts.constraints.domain.constraints import (
    Constraints,
    compensation_policy,
    water_supply_policy,
)
from backend.contexts.connectivity.domain.connectivity import Groups, Lambda
from backend.contexts.runs.domain.run_result import ResponseArtifact
from backend.contexts.schedule.domain.schedule import Role, Schedule
from backend.shared.hashing import canonical_bytes, hash_schedule
from backend.contexts.connectivity.domain.groups import (
    GroupingParams,
    build_groups,
    group_hash,
    lambda_hash,
)
from backend.contexts.connectivity.domain.measure import load_lambda
from backend.contexts.economics.infrastructure.normatives_io import load_normatives
from backend.contexts.economics.application.base_case import load_response_artifact
from backend.contexts.policy.domain.fixed_point import Evaluation
from backend.contexts.policy.domain.flags import DEFAULT_RULE_FLAGS, RuleFlags
from backend.contexts.schedule.domain.build import build_schedule
from backend.contexts.schedule.domain.lossless import parse_schedule
from backend.contexts.schedule.domain.canonical import canonicalize
from backend.contexts.surrogate.application.adapter import ResponseAdapter
from backend.contexts.surrogate.application.ensemble import TrajectoryEnsemble
from backend.contexts.surrogate.domain.features import ScheduleFeatureizer
from backend.contexts.surrogate.application.model import TrajectorySurrogate
from backend.contexts.surrogate.infrastructure.model_z_context import ModelZFeatureArtifact
from backend.contexts.surrogate.domain.npv_head import ScenarioNpvHead
from backend.shared.errors import DomainError


from backend.contexts.reservoir.domain.horizon import HORIZON


_SCHEDULE_INCLUDE = "Model_Z_sch.inc"


def _trivial_connectivity(schedule: Schedule) -> tuple[Lambda, Groups]:
    wells = schedule.meta.wells
    roles = {well: schedule.initial_state[well].role for well in wells}
    producers = tuple(well for well in wells if roles[well] is Role.PROD)
    injectors = tuple(well for well in wells if roles[well] is Role.INJ)
    influence = Lambda(
        window_start=schedule.meta.t0,
        window_end=schedule.meta.t0,
        producers=producers,
        injectors=injectors,
        matrix=tuple(tuple(0.0 for _ in injectors) for _ in producers),
        lag_months=0,
        amplitude=0.0,
        stability=0.0,
        rank=0,
        condition_number=0.0,
        achievability_ok={well: False for well in injectors},
    )
    groups_by_id = {"ALL": wells}
    params = GroupingParams()
    groups = Groups(
        groups=groups_by_id,
        lambda_hash=lambda_hash(influence),
        group_hash=group_hash(groups_by_id, influence, params),
    )
    return influence, groups


def _build_reference(
    base_schedule: Schedule,
    feature_context: ModelZFeatureArtifact,
    model: TrajectorySurrogate | TrajectoryEnsemble,
) -> tuple[Schedule | None, RawModelOutput | None, str]:
    reference_schedule = canonicalize(base_schedule)
    try:
        model_input = replace(
            ScheduleFeatureizer().transform(reference_schedule, feature_context.context),
            lambda_edges=(),
        )
        reference_response = model.predict(model_input).output
    except (DomainError, ValueError, AttributeError, TypeError) as error:
        return None, None, f"absent: the surrogate forecast on the reference was not built: {error}"
    if reference_response.canonical_schedule_hash != hash_schedule(reference_schedule):
        return (
            None,
            None,
            "absent: the reference forecast is bound to a different schedule",
        )
    return (
        reference_schedule,
        reference_response,
        "base-case-schedule+surrogate-prediction",
    )


def load_environment(
    *,
    model_dir: Path,
    normatives_path: Path,
    response_path: Path,
    checkpoint_path: Path,
    feature_context_path: Path,
    oil_density_t_per_m3: float = 0.9131,
    lambda_path: Path | None = None,
    npv_head_path: Path | None = None,
    npv_calibration_path: Path | None = None,
    scenario_ood_path: Path | None = None,
    physics_gate: bool = True,
    constraints: Constraints | None = None,
    ood_threshold: float = 0.0,
    ood_soft_penalty: bool = False,
    ood_penalty_per_unit: float = 0.0,
    lambda_strict: bool | None = None,
) -> SearchEnvironment:
    strict_lambda = _lambda_strict_enabled() if lambda_strict is None else lambda_strict
    case_constraints = Constraints() if constraints is None else constraints
    water_supply_policy(case_constraints)
    compensation_policy(case_constraints)
    if ood_threshold < 0.0:
        raise ScheduleSearchError("OOD threshold must not be negative")
    if ood_soft_penalty and ood_penalty_per_unit <= 0.0:
        raise ScheduleSearchError(
            f"the soft penalty is enabled but the rate {ood_penalty_per_unit} is not positive: "
            "a penalty that does not punish leaving the domain is no different "
            "from removing the guard entirely"
        )
    raw = (Path(model_dir) / _SCHEDULE_INCLUDE).read_bytes()
    parsed = parse_schedule(raw)
    base_schedule = build_schedule(parsed, raw, provenance="policy-search-base")
    real_history = load_response_artifact(response_path)
    normatives = load_normatives(normatives_path)
    policies = default_policies()
    feature_context = ModelZFeatureArtifact.load(feature_context_path)
    expected_dates = tuple(parsed.dates[parsed.t0_deck_date_index:])
    if tuple(feature_context.context.control_dates) != expected_dates:
        raise ScheduleSearchError(
            "The weights period does not match the deck period: compatible "
            "weights/context are needed for the new case; changing AIOS_HORIZON_PATH "
            "on its own does not carry the surrogate over to another period"
        )
    if len(parsed.dates) != HORIZON.n_deck_dates or parsed.t0_deck_date_index != HORIZON.history_offset:
        raise ScheduleSearchError("The deck dimensions do not match AIOS_HORIZON_PATH")
    model = (
        TrajectoryEnsemble.load(checkpoint_path)
        if Path(checkpoint_path).suffix == ".json"
        else TrajectorySurrogate.load(checkpoint_path)
    )
    scenario_ood = ScenarioDensityDomain.load(scenario_ood_path) if scenario_ood_path is not None else None
    if scenario_ood is not None and scenario_ood.dataset_hash != model.dataset_hash:
        raise ScheduleSearchError("scenario OOD dataset differs from trajectory checkpoint")
    head_path = npv_head_path
    if head_path is None:
        adjacent_head = Path(checkpoint_path).parent / "npv_head.pt"
        head_path = adjacent_head if adjacent_head.is_file() else None
    npv_head = load_direct_npv_head(head_path) if head_path is not None else None
    if npv_head is not None:
        _validate_npv_head_compatibility(npv_head, model, feature_context_path)
    npv_calibration = (
        NpvCalibration.load(npv_calibration_path, model_version=model.version)
        if npv_calibration_path is not None
        else None
    )
    _validate_npv_scoring_is_unambiguous(npv_head, npv_calibration)
    if lambda_path is None:
        lambda_, groups = _trivial_connectivity(base_schedule)
    else:
        lambda_ = load_lambda(lambda_path)
        groups, _ = build_groups(
            lambda_, GroupingParams(), extra_wells=base_schedule.meta.wells
        )
    flags = RuleFlags(enabled=dict(DEFAULT_RULE_FLAGS))
    reference_schedule, reference_response, reference_origin = _build_reference(
        base_schedule, feature_context, model
    )
    provenance = MappingProxyType(
        {
            "reference": reference_origin,
            "reference_schedule_hash": (
                hash_schedule(reference_schedule)
                if reference_schedule is not None
                else "none"
            ),
            "feature_context_path": str(feature_context_path),
            **npv_blend_provenance(npv_head),
            **lambda_sync_provenance(
                lambda_,
                feature_context,
                lambda_path,
                strict=strict_lambda,
            ),
        }
    )
    return SearchEnvironment(
        base_schedule=base_schedule,
        real_history=real_history,
        normatives=normatives,
        policies=policies,
        oil_density_t_per_m3=oil_density_t_per_m3,
        feature_context=feature_context,
        model=model,
        control_dates=tuple(feature_context.context.control_dates),
        deck_dates=tuple(parsed.dates),
        t0_deck_date_index=parsed.t0_deck_date_index,
        groups=groups,
        lambda_=lambda_,
        constraints=case_constraints,
        flags=flags,
        npv_head=npv_head,
        npv_calibration=npv_calibration,
        scenario_ood=scenario_ood,
        physics_gate=physics_gate,
        ood_threshold=ood_threshold,
        ood_soft_penalty=ood_soft_penalty,
        ood_penalty_per_unit=ood_penalty_per_unit,
        reference_schedule=reference_schedule,
        reference_response=reference_response,
        provenance=provenance,
    )


def make_evaluator(env: SearchEnvironment, *, with_sigma: bool = False):
    featureizer = ScheduleFeatureizer()
    adapter = ResponseAdapter()

    def evaluator(schedule: Schedule) -> Evaluation:
        model_input = replace(
            featureizer.transform(schedule, env.feature_context.context),
            lambda_edges=(),
        )
        if env.ood_soft_penalty:
            scenario_excess = _scenario_ood_excess(
                model_input, env.model, env.scenario_ood
            )
            scored = env.model.predict(model_input)
            node_excess = _ood_threshold_excess(scored.ood, env.ood_threshold)
            penalty_excess = max(
                0.0
                if scenario_excess is None
                else scenario_excess[0] - float(env.scenario_ood.threshold),
                0.0 if node_excess is None else node_excess[0] - env.ood_threshold,
            )
        else:
            _enforce_scenario_ood(model_input, env.model, env.scenario_ood)
            scored = env.model.predict(model_input)
            _enforce_ood_threshold(scored.ood, env.ood_threshold)
            penalty_excess = 0.0
        evaluator.ood_exceedances = format_ood_exceedances(  # type: ignore[attr-defined]
            scored.ood
        )
        physics = full_physics_report(env, schedule, scored.output)
        _enforce_physics(physics, env.physics_gate)
        evaluator.physics_report = physics  # type: ignore[attr-defined]
        states, intervals = adapter.adapt(
            scored.output, schedule, env.real_history, env.control_dates
        )
        identity = {"model_version": env.model.version, "schedule_hash": hash_schedule(schedule)}
        response = ResponseArtifact(
            source_run_id=f"surrogate-search:{env.model.version[:12]}",
            response_hash=hashlib.sha256(canonical_bytes(identity)).hexdigest(),
            state_at_date=states,
            interval_response=intervals,
        )
        npv_parts = predict_economics(env, model_input, response)
        npv = npv_parts['blended']
        economic_ood = (
            env.npv_head.predict_with_domain(model_input)[1]
            if isinstance(env.npv_head, ScenarioNpvHead) else 0.0
        )
        ood_score = max(scored.ood.score, economic_ood)
        if env.ood_soft_penalty and penalty_excess > 0.0:
            penalized = apply_ood_penalty(
                npv, penalty_excess, env.ood_penalty_per_unit
            )
            npv_parts = dict(
                npv_parts,
                blended=penalized,
                unpenalized_blended=float(npv),
                ood_penalty_excess=float(penalty_excess),
            )
            npv = penalized
        return Evaluation(
            npv=npv,
            state=PolicyFeedback(response=response, schedule=schedule),
            ood_score=ood_score,
            npv_parts=MappingProxyType({
                name: float(value) for name, value in npv_parts.items()
            }),
            sigma=(
                ensemble_npv_sigma(env, adapter, schedule, model_input)
                if with_sigma
                else None
            ),
            physics=MappingProxyType(physics_counters(physics)),
            ood_worst=format_ood_worst(scored.ood),
        )

    evaluator.reference_schedule = env.reference_schedule  # type: ignore[attr-defined]
    evaluator.reference_response = env.reference_response  # type: ignore[attr-defined]
    evaluator.ood_exceedances = ()  # type: ignore[attr-defined]
    return evaluator
