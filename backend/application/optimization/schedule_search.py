from __future__ import annotations

from backend.ml.surrogate.npv_block_head import BlockKernelNpvHead, load_direct_npv_head
from backend.ml.surrogate.npv_economic_features import scenario_feature_vector
from backend.ml.surrogate.model import _features
from backend.ml.surrogate.ood import Exceedance, OodScore, worst_offenders
from backend.ml.surrogate.physics_checks import (
    Invariant,
    PhysicsCheckError,
    PhysicsReport,
    Severity,
    check_pair,
    check_prediction,
    severity_of,
)
from backend.ml.surrogate.scenario_ood import ScenarioDensityDomain
from backend.ml.surrogate.npv_calibration import NpvCalibration
from backend.ml.surrogate.raw_model_output import RawModelOutput


import hashlib
import math
import os
from dataclasses import dataclass, replace
from datetime import date
from pathlib import Path
from types import MappingProxyType
from typing import Callable, Mapping, Sequence

from backend.domain.configuration.schema import default_policies
from backend.core.contracts import (
    Constraints,
    ControlEvent,
    EventKind,
    Groups,
    Lambda,
    N_INTERVALS,
    NormativeSet,
    Policies,
    ResponseArtifact,
    OperatingStatus,
    Role,
    Schedule,
    Theta,
    canonical_bytes,
    compensation_policy,
    hash_schedule,
    water_supply_policy,
)
from backend.domain.connectivity.groups import GroupingParams, build_groups, group_hash, lambda_hash
from backend.domain.connectivity.measure import load_lambda
from backend.domain.economics import analyze_base_case, load_normatives, load_response_artifact
from backend.domain.policy.budget import liquid_limit_for_step
from backend.domain.policy.agents.projection import (
    HardConstraints,
    project_to_hard_constraints,
)
from backend.domain.policy.fixed_point import Evaluation
from backend.domain.policy.flags import DEFAULT_RULE_FLAGS, RuleFlags
from backend.domain.policy.hierarchy import observations_by_group, run_step
from backend.domain.policy.memory import PolicyMemory, esp_size_for
from backend.domain.policy.rules import r3
from backend.domain.policy.state import PolicyState, RuleContext, WellObservation
from backend.domain.policy.trace import RunTrace
from backend.domain.schedule import build_schedule, parse_schedule
from backend.domain.schedule.canonical import canonicalize
from backend.ml.surrogate.adapter import ResponseAdapter
from backend.ml.surrogate.ensemble import TrajectoryEnsemble
from backend.ml.surrogate.features import ScheduleFeatureizer
from backend.ml.surrogate.model import TrajectorySurrogate
from backend.ml.surrogate.model_z_context import ModelZFeatureArtifact
from backend.ml.surrogate.npv_head import ScenarioNpvHead

Projection = Callable[[ControlEvent, HardConstraints], ControlEvent]

UNCONSTRAINED_WELLS = HardConstraints(well_cap_m3_per_day={})

_UNCONSTRAINED_FIELD_LIMIT_M3_PER_DAY = 1.0e7

PHYSICAL_HEADROOM = 1.2
SETPOINT_STEP_M3_PER_DAY = 1.0
WATER_COMMAND_SAFETY_FACTOR = 0.95
_HISTORY_DECK_OFFSET = 146
_SCHEDULE_INCLUDE = "Model_Z_sch.inc"
_DIFFERENTIAL_INVARIANT_NAMES: tuple[str, ...] = (
    Invariant.INJECTION_RESPONSE.value,
    Invariant.MATERIAL_BALANCE.value,
)
OOD_EXCEEDANCE_LIMIT = 5


class ScheduleSearchError(ValueError):
    pass


class LambdaDesyncError(ScheduleSearchError):
    pass


LAMBDA_STRICT_ENV = "AIOS_LAMBDA_STRICT"


def _lambda_strict_enabled(environ: Mapping[str, str] | None = None) -> bool:
    env = os.environ if environ is None else environ
    raw = env.get(LAMBDA_STRICT_ENV)
    if raw is None:
        return False
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def npv_blend_provenance(npv_head: object | None) -> dict[str, str]:
    if npv_head is None:
        return {
            "npv_head_version": "none",
            "npv_blend_mode": "absent: голова прямого прогноза не загружена",
            "npv_physical_weight": "none",
            "npv_direct_weight": "none",
            "npv_physical_ensemble_version": "none",
            "npv_blend_provenance_hash": "none",
        }
    weight = getattr(npv_head, "physical_npv_weight", None)
    if weight is None:
        raise ScheduleSearchError(
            "голова ЧДД не сообщает physical_npv_weight: долю физической части "
            "бленда нельзя записать в провенанс, а прогноз ЧДД без неё "
            "невоспроизводим"
        )
    physical = float(weight)
    if not math.isfinite(physical) or not 0.0 <= physical <= 1.0:
        raise ScheduleSearchError(
            f"доля физической части бленда {physical!r} вне отрезка [0, 1]: "
            "провенанс ЧДД описывал бы несуществующую смесь"
        )
    return {
        "npv_head_version": str(getattr(npv_head, "version", "") or "unversioned"),
        "npv_blend_mode": "direct-only" if physical == 0.0 else "physical-blend",
        "npv_physical_weight": repr(physical),
        "npv_direct_weight": repr(1.0 - physical),
        "npv_physical_ensemble_version": str(
            getattr(npv_head, "physical_ensemble_version", "") or "none"
        ),
        "npv_blend_provenance_hash": str(
            getattr(npv_head, "physical_blend_provenance_hash", "") or "none"
        ),
    }


def _context_lambda_hashes(feature_context: ModelZFeatureArtifact) -> tuple[str, ...]:
    return tuple(lambda_hash(window) for window in feature_context.context.lambda_windows)


def lambda_sync_provenance(
    lambda_: Lambda,
    feature_context: ModelZFeatureArtifact,
    lambda_path: Path | None,
    *,
    strict: bool,
) -> dict[str, str]:
    search_hash = lambda_hash(lambda_)
    context_hashes = _context_lambda_hashes(feature_context)
    record = {
        "lambda_path": "none: связность не измерялась" if lambda_path is None else str(lambda_path),
        "lambda_window": f"{lambda_.window_start}..{lambda_.window_end}",
        "lambda_search_hash": search_hash,
        "lambda_context_hashes": ",".join(context_hashes) if context_hashes else "none",
        "lambda_context_source_hash": feature_context.lambda_source_hash,
        "lambda_context_dataset_hash": feature_context.dataset_hash,
        "lambda_context_training_scenarios": str(feature_context.n_training_scenarios),
        "lambda_strict": "true" if strict else "false",
    }
    if lambda_path is None:
        record["lambda_sync"] = "not-applicable"
        record["lambda_sync_detail"] = (
            "поиск идёт на нулевой связности, сверять с обучающей λ нечего"
        )
        return record
    if not context_hashes:
        message = (
            "контекст признаков не содержит ни одного окна λ: на какой матрице "
            "связности обучались признаки — установить нельзя, поэтому "
            "рассинхронизацию с λ поиска обнаружить невозможно"
        )
        record["lambda_sync"] = "unknown"
        record["lambda_sync_detail"] = message
        if strict:
            raise LambdaDesyncError(message)
        return record
    if search_hash in context_hashes:
        record["lambda_sync"] = "match"
        record["lambda_sync_detail"] = (
            f"λ поиска {search_hash} совпала с окном, на котором обучался контекст"
        )
        return record
    message = (
        f"λ поиска ({lambda_path}, окно {lambda_.window_start}..{lambda_.window_end}, "
        f"хеш {search_hash}) не совпадает ни с одним окном, на котором обучался "
        f"контекст признаков (хеши {', '.join(context_hashes)}): поиск считает на "
        "одной матрице связности, а признаки обучены на другой, поэтому прогноз "
        "смещён систематически и по самому прогнозу это не видно"
    )
    record["lambda_sync"] = "desync"
    record["lambda_sync_detail"] = message
    if strict:
        raise LambdaDesyncError(message)
    return record


def _validate_npv_head_compatibility(
    npv_head: object, model: object, feature_context_path: Path | str
) -> None:
    context_hash = getattr(npv_head, "feature_context_sha256", "")
    if context_hash:
        actual = hashlib.sha256(Path(feature_context_path).read_bytes()).hexdigest()
        if context_hash != actual:
            raise ScheduleSearchError("NPV head обучен на другом feature context")
    elif getattr(npv_head, "dataset_hash", None) != getattr(
        model, "dataset_hash", None
    ):
        raise ScheduleSearchError(
            "NPV head и trajectory model обучены на разных данных"
        )
    if getattr(npv_head, "wells", None) != getattr(model, "wells", None):
        raise ScheduleSearchError(
            "NPV head и trajectory model имеют разный фонд скважин"
        )
    if getattr(npv_head, "static_feature_names", None) != getattr(
        model, "static_feature_names", None
    ):
        raise ScheduleSearchError("NPV head и trajectory model имеют разную статику")
    physical_weight = float(getattr(npv_head, "physical_npv_weight", 0.0))
    if physical_weight > 0.0 and getattr(
        npv_head, "physical_ensemble_version", ""
    ) != getattr(model, "version", None):
        raise ScheduleSearchError(
            "NPV blend заморожен под другую trajectory ensemble"
        )


_AMBIGUOUS_NPV_SCORING = (
    "одновременно заданы аффинная калибровка ЧДД и голова прямого прогноза: "
    "калибровка подобрана на сыром физическом ЧДД и к бленду головы "
    "неприменима — итоговое число было бы посчитано не тем, чем заявлено; "
    "оставьте один механизм"
)


def _validate_npv_scoring_is_unambiguous(
    npv_head: object | None, npv_calibration: object | None
) -> None:
    if npv_head is not None and npv_calibration is not None:
        raise ScheduleSearchError(_AMBIGUOUS_NPV_SCORING)


class OutOfDomainScheduleError(ScheduleSearchError):

    def __init__(
        self,
        score: float,
        description: str,
        exceedances: Sequence[Mapping[str, object]] = (),
    ) -> None:
        self.score = float(score)
        self.description = description
        self.exceedances = tuple(dict(item) for item in exceedances)
        super().__init__(
            f"кандидат вне области обучения: ood_score={score:.6g}; {description}"
        )


class PhysicallyImpossibleScheduleError(ScheduleSearchError):

    def __init__(
        self,
        counts: Mapping[str, int],
        description: str,
        missing_invariants: Sequence[str] = (),
    ) -> None:
        self.counts = dict(counts)
        self.description = description
        self.missing_invariants = tuple(missing_invariants)
        super().__init__(f"кандидат физически невозможен: {description}")


def missing_invariants(report: PhysicsReport) -> tuple[str, ...]:
    evaluated = {invariant.value for invariant in report.evaluated}
    return tuple(
        invariant.value for invariant in Invariant if invariant.value not in evaluated
    )


def _incompleteness_description(report: PhysicsReport) -> str:
    parts: list[str] = []
    for name in missing_invariants(report):
        reason = report.skipped.get(name)
        parts.append(name if reason is None else f"{name} ({reason})")
    return (
        "physics_complete=false: проверка неполная, не посчитаны инварианты: "
        + "; ".join(parts)
    )


def _enforce_physics(
    report: PhysicsReport,
    enabled: bool,
    baseline: Mapping[str, int] | None = None,
) -> None:

    if not enabled or report.admissible:
        return
    if not report.complete:
        missing = missing_invariants(report)
        raise PhysicallyImpossibleScheduleError(
            {}, _incompleteness_description(report), missing
        )
    blocking = {
        name: count
        for name, count in sorted(report.counts.items())
        if severity_of(name) is Severity.BLOCKING
    }
    description = "physics_complete=true; " + ", ".join(
        f"{name}×{count}" for name, count in blocking.items()
    )
    example = next(
        (flag for flag in report.examples if flag.severity is Severity.BLOCKING), None
    )
    if example is not None:
        description += (
            f"; например скважина {example.well}, шаг {example.control_step}: "
            f"{example.detail}"
        )
    raise PhysicallyImpossibleScheduleError(blocking, description)


def _scenario_ood_excess(
    model_input, model, domain: ScenarioDensityDomain | None
) -> tuple[float, str] | None:
    if domain is None:
        return None
    x, well_index = _features(model_input, model.wells, scenario_context=False)
    vector = scenario_feature_vector(
        x, well_index, n_wells=len(model.wells), feature_set="economic"
    )
    score = domain.score(vector[: domain.feature_width])
    if score <= domain.threshold:
        return None
    return score, (
        f"совместная плотность расписания {score:.4g} выше порога "
        f"{domain.threshold:.4g} (квантиль {domain.threshold_quantile} по валидации)"
    )


def _enforce_scenario_ood(
    model_input, model, domain: ScenarioDensityDomain | None
) -> None:

    exceeded = _scenario_ood_excess(model_input, model, domain)
    if exceeded is None:
        return
    raise OutOfDomainScheduleError(*exceeded)


def exceedance_record(item: Exceedance) -> dict[str, object]:
    return {
        "feature": item.feature,
        "well": item.well,
        "control_step": int(item.control_step),
        "value": None if math.isnan(item.value) else float(item.value),
        "train_low": None if math.isnan(item.low) else float(item.low),
        "train_high": None if math.isnan(item.high) else float(item.high),
        "score": None if math.isinf(item.score) else float(item.score),
        "unbounded": bool(math.isinf(item.score)),
    }


def format_ood_exceedances(
    ood: OodScore, limit: int = OOD_EXCEEDANCE_LIMIT
) -> tuple[dict[str, object], ...]:
    if not ood.exceedances:
        return ()
    return tuple(exceedance_record(item) for item in worst_offenders(ood, limit))


def _ood_threshold_excess(
    ood: OodScore, threshold: float | None
) -> tuple[float, str, tuple[dict[str, object], ...]] | None:
    if threshold is None or ood.inside(threshold):
        return None
    worst = ood.worst
    description = (
        "неизвестное превышение"
        if worst is None
        else (
            f"{worst.feature}, скважина {worst.well}, "
            f"шаг {worst.control_step}, значение {worst.value:.6g}, "
            f"train [{worst.low:.6g}, {worst.high:.6g}]"
        )
    )
    return ood.score, description, format_ood_exceedances(ood)


def _enforce_ood_threshold(ood: OodScore, threshold: float | None) -> None:

    exceeded = _ood_threshold_excess(ood, threshold)
    if exceeded is None:
        return
    raise OutOfDomainScheduleError(*exceeded)


def ood_penalty_factor(excess: float, penalty_per_unit: float) -> float:
    if not math.isfinite(excess) or excess < 0.0:
        raise ScheduleSearchError(
            f"превышение области применимости {excess!r} не конечно или отрицательно: "
            "мягкий штраф посчитать не по чему"
        )
    if not math.isfinite(penalty_per_unit) or penalty_per_unit < 0.0:
        raise ScheduleSearchError(
            f"ставка мягкого штрафа {penalty_per_unit!r} не конечна или отрицательна"
        )
    return math.exp(-penalty_per_unit * excess)


def apply_ood_penalty(npv: float, excess: float, penalty_per_unit: float) -> float:
    if not math.isfinite(npv):
        raise ScheduleSearchError(
            f"ЧДД {npv!r} не конечен: мягкий штраф области применимости неприменим"
        )
    factor = ood_penalty_factor(excess, penalty_per_unit)
    penalized = npv * factor if npv >= 0.0 else npv / factor
    if not math.isfinite(penalized):
        raise ScheduleSearchError(
            f"мягкий штраф дал неконечный ЧДД: npv={npv!r}, excess={excess!r}, "
            f"ставка={penalty_per_unit!r}"
        )
    return penalized


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


@dataclass(frozen=True, slots=True)
class SearchEnvironment:

    base_schedule: Schedule
    real_history: ResponseArtifact
    normatives: NormativeSet
    policies: Policies
    oil_density_t_per_m3: float
    feature_context: ModelZFeatureArtifact
    model: TrajectorySurrogate | TrajectoryEnsemble
    control_dates: tuple[date, ...]
    deck_dates: tuple[date, ...]
    t0_deck_date_index: int
    groups: Groups
    lambda_: Lambda
    constraints: Constraints
    flags: RuleFlags
    npv_head: ScenarioNpvHead | BlockKernelNpvHead | None = None
    scenario_ood: ScenarioDensityDomain | None = None
    npv_calibration: NpvCalibration | None = None
    physics_gate: bool = True
    ood_threshold: float = 0.0
    ood_soft_penalty: bool = False
    ood_penalty_per_unit: float = 0.0
    reference_schedule: Schedule | None = None
    reference_response: RawModelOutput | None = None
    provenance: Mapping[str, str] = MappingProxyType({})

    @property
    def has_reference(self) -> bool:
        return self.reference_schedule is not None and self.reference_response is not None


@dataclass(frozen=True, slots=True)
class PolicyFeedback:

    response: ResponseArtifact
    schedule: Schedule


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
    except (ValueError, AttributeError, TypeError) as error:
        return None, None, f"absent: прогноз суррогата на опоре не построен: {error}"
    if reference_response.canonical_schedule_hash != hash_schedule(reference_schedule):
        return (
            None,
            None,
            "absent: прогноз опоры привязан к другому расписанию",
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
        raise ScheduleSearchError("OOD threshold не может быть отрицательным")
    if ood_soft_penalty and ood_penalty_per_unit <= 0.0:
        raise ScheduleSearchError(
            f"мягкий штраф включён, а ставка {ood_penalty_per_unit} не положительна: "
            "штраф, не наказывающий за выход, ничем не отличается от снятой охраны"
        )
    raw = (Path(model_dir) / _SCHEDULE_INCLUDE).read_bytes()
    parsed = parse_schedule(raw)
    base_schedule = build_schedule(parsed, raw, provenance="policy-search-base")
    real_history = load_response_artifact(response_path)
    normatives = load_normatives(normatives_path)
    policies = default_policies()
    feature_context = ModelZFeatureArtifact.load(feature_context_path)
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


def _commission_steps(schedule: Schedule) -> dict[str, int]:

    steps: dict[str, int] = {}
    for well, state in schedule.initial_state.items():
        if state.role is not Role.NONE:
            steps[well] = 0
    for event in schedule.fixed_deck_events:
        if event.operator in ("WCONPROD", "WCONINJE"):
            steps.setdefault(event.well, event.control_step)
    return steps


def _flow_start_steps(
    schedule: Schedule,
    initial_rates: Mapping[str, tuple[float, float, float]] | None = None,
) -> dict[str, int]:

    commissioned = _commission_steps(schedule)
    first_completion: dict[str, int] = {}
    for event in schedule.fixed_deck_events:
        if event.operator not in ("COMPDAT", "COMPDATMD"):
            continue
        first_completion[event.well] = min(
            event.control_step,
            first_completion.get(event.well, event.control_step),
        )
    result: dict[str, int] = {}
    for well, step in commissioned.items():
        initial = schedule.initial_state.get(well)
        initial_rate = (initial_rates or {}).get(well, (0.0, 0.0, 0.0))
        contradictory_open = (
            initial is not None
            and initial.role is not Role.NONE
            and initial.operating_status is OperatingStatus.OPEN
            and initial.setpoint > 0.0
            and max(initial_rate[0], initial_rate[2]) <= 0.0
            and well in first_completion
        )
        if (
            initial is not None
            and initial.role is not Role.NONE
            and not contradictory_open
        ):
            result[well] = 0
            continue
        result[well] = max(step, first_completion.get(well, step))
    return result


def _role_at_commission(schedule: Schedule) -> dict[str, Role]:
    roles: dict[str, Role] = {}
    for well, state in schedule.initial_state.items():
        if state.role is not Role.NONE:
            roles[well] = state.role
    for event in schedule.fixed_deck_events:
        if event.operator == "WCONPROD":
            roles.setdefault(event.well, Role.PROD)
        elif event.operator == "WCONINJE":
            roles.setdefault(event.well, Role.INJ)
    return roles


def _rates_at(
    response: ResponseArtifact, deck_date_index: int
) -> dict[str, tuple[float, float, float]]:
    return {
        item.well: (item.liquid_rate, item.oil_rate, item.injection_rate)
        for item in response.state_at_date
        if item.deck_date_index == deck_date_index
    }


def _build_policy_state(
    control_step: int,
    response: ResponseArtifact,
    *,
    wells: tuple[str, ...],
    current_role: Mapping[str, Role],
    current_is_open: Mapping[str, bool],
    current_setpoint: Mapping[str, float],
    commission_step: Mapping[str, int],
    oil_density_t_per_m3: float,
) -> PolicyState:
    rates = _rates_at(response, _HISTORY_DECK_OFFSET + control_step)
    observations: dict[str, WellObservation] = {}
    for well in wells:
        if control_step < commission_step.get(well, 0):
            continue
        role = current_role[well]
        if role is Role.NONE:
            continue
        liquid, oil, injection = rates.get(well, (0.0, 0.0, 0.0))
        liquid = max(liquid, 0.0)
        oil = max(0.0, min(oil, liquid * oil_density_t_per_m3 * (1.0 - 1e-9)))
        observations[well] = WellObservation(
            well=well,
            role=role,
            is_open=current_is_open[well],
            liquid_rate_m3_per_day=liquid,
            oil_rate_t_per_day=oil,
            injection_rate_m3_per_day=max(injection, 0.0),
            setpoint_m3_per_day=current_setpoint[well],
        )
    return PolicyState(control_step=control_step, wells=observations)


def _group_injection_offtake(
    state: PolicyState, groups: Groups
) -> tuple[dict[str, float], dict[str, float]]:

    by_group = observations_by_group(state, groups)
    injection: dict[str, float] = {}
    offtake: dict[str, float] = {}
    for group_id, wells in by_group.items():
        injection[group_id] = sum(
            w.injection_rate_m3_per_day for w in wells if w.role is Role.INJ and w.is_open
        )
        offtake[group_id] = sum(
            w.liquid_rate_m3_per_day for w in wells if w.role is Role.PROD and w.is_open
        )
    return injection, offtake


def _apply_decision(
    event: ControlEvent,
    *,
    current_role: dict[str, Role],
    current_is_open: dict[str, bool],
    current_setpoint: dict[str, float],
    memory: PolicyMemory,
) -> PolicyMemory:
    if event.kind is EventKind.OPEN:
        current_is_open[event.well] = True
    elif event.kind is EventKind.SHUT:
        current_is_open[event.well] = False
    elif event.kind in (EventKind.SET_LRAT, EventKind.SET_RATE):
        current_setpoint[event.well] = event.value if event.value is not None else 0.0
    elif event.kind is EventKind.CONVERT_INJ:
        current_role[event.well] = Role.INJ
        current_is_open[event.well] = True
        memory = memory.updated(
            event.well, memory.of(event.well).converted_at(event.control_step)
        )
    return memory


def _advance_memory(state: PolicyState, context: RuleContext, *, esp_catalog) -> PolicyMemory:
    memory = context.memory
    for well, observation in state.wells.items():
        current = memory.of(well)
        if observation.role is Role.PROD:
            current = r3.advance(state, replace(context, memory=memory), well)
        if observation.liquid_rate_m3_per_day > 0.0:
            needed = esp_size_for(esp_catalog, observation.liquid_rate_m3_per_day)
            if needed.nominal > current.esp_nominal_m3_per_day:
                current = current.with_esp(needed.nominal)
        memory = memory.updated(well, current)
    return memory


def _physical_caps(schedule: Schedule) -> tuple[dict[str, float], float]:

    per_well: dict[str, float] = {}
    by_step_injection: dict[int, float] = {}
    for event in schedule.control_events:
        if event.value is None or event.value <= 0.0:
            continue
        if event.kind not in (EventKind.SET_RATE, EventKind.SET_LRAT):
            continue
        previous = per_well.get(event.well, 0.0)
        per_well[event.well] = max(previous, event.value * PHYSICAL_HEADROOM)
        if event.kind is EventKind.SET_RATE:
            by_step_injection[event.control_step] = (
                by_step_injection.get(event.control_step, 0.0) + event.value
            )
    field_limit = max(by_step_injection.values(), default=0.0) * PHYSICAL_HEADROOM
    if field_limit <= 0.0:
        raise ScheduleSearchError(
            "в базовом расписании нет ни одной положительной уставки закачки: "
            "физический потолок месторождения выводить не из чего"
        )
    return per_well, field_limit


def _interval_produced_water_rate_m3_per_day(
    response: ResponseArtifact,
    control_step: int,
    control_dates: Sequence[date],
    oil_density_t_per_m3: float,
) -> float:

    if oil_density_t_per_m3 <= 0.0:
        raise ScheduleSearchError("плотность нефти должна быть положительной")
    days = (control_dates[control_step + 1] - control_dates[control_step]).days
    if days <= 0:
        raise ScheduleSearchError(
            f"control_step={control_step}: неположительная длина интервала"
        )
    water_volume = 0.0
    for item in response.interval_response:
        if item.control_step != control_step:
            continue
        oil_volume = max(0.0, item.oil_mass_delta) / oil_density_t_per_m3
        water_volume += max(0.0, item.liquid_volume_delta - oil_volume)
    return water_volume / days


SOURCE_PHYSICAL_HEADROOM = "physical_headroom"
SOURCE_CASE_INJECTION_LIMIT = "case_injection_limit"
SOURCE_WATER_BALANCE = "water_balance"
SOURCE_COMMAND_MARGIN = "command_margin"
SOURCE_WATER_BALANCE_REPAIR = "water_balance_repair"

UNCONSTRAINED_BUDGET_M3_PER_DAY = float("inf")


@dataclass(frozen=True, slots=True)
class InjectionBudget:

    control_step: int
    limit_m3_per_day: float
    binding_source: str
    contributions: tuple[tuple[str, float], ...]

    @property
    def unconstrained(self) -> bool:
        return not math.isfinite(self.limit_m3_per_day)

    def as_trace_entry(self) -> dict[str, object]:
        return {
            "control_step": self.control_step,
            "limit_m3_per_day": self.limit_m3_per_day,
            "binding_source": self.binding_source,
            "contributions": {name: value for name, value in self.contributions},
        }


def injection_budget_for_step(
    *,
    control_step: int,
    constraints: Constraints,
    year: int,
    produced_water_by_step: Sequence[float],
    physical_limit_m3_per_day: float | None = None,
    command_margin: float = 1.0,
) -> InjectionBudget:

    if not 0.0 < command_margin <= 1.0:
        raise ScheduleSearchError(
            f"control_step={control_step}: запас команды закачки должен лежать "
            f"в диапазоне (0, 1], получено {command_margin}"
        )
    contributions: list[tuple[str, float]] = []
    if physical_limit_m3_per_day is not None:
        contributions.append(
            (SOURCE_PHYSICAL_HEADROOM, float(physical_limit_m3_per_day))
        )
    explicit = constraints.injection_limits.get(year)
    if explicit is not None:
        contributions.append((SOURCE_CASE_INJECTION_LIMIT, float(explicit)))

    water = water_supply_policy(constraints)
    if water.enabled:
        source_step = control_step - water.lag_steps
        produced = (
            produced_water_by_step[source_step]
            if 0 <= source_step < len(produced_water_by_step)
            else 0.0
        )
        water_limit = water.limit(produced)
        if water_limit is None:
            raise ScheduleSearchError(
                f"control_step={control_step}: политика воды включена, но "
                "потолок закачки по водному балансу не посчитан"
            )
        contributions.append((SOURCE_WATER_BALANCE, float(water_limit)))

    if not contributions:
        return InjectionBudget(
            control_step=control_step,
            limit_m3_per_day=UNCONSTRAINED_BUDGET_M3_PER_DAY,
            binding_source="none",
            contributions=(),
        )

    binding_source, raw_limit = min(contributions, key=lambda item: item[1])
    limit = max(0.0, raw_limit)
    if command_margin < 1.0:
        limit *= command_margin
        contributions.append((SOURCE_COMMAND_MARGIN, limit))
        binding_source = SOURCE_COMMAND_MARGIN
    return InjectionBudget(
        control_step=control_step,
        limit_m3_per_day=limit,
        binding_source=binding_source,
        contributions=tuple(contributions),
    )


def _field_limit_for_step(
    *,
    physical_limit_m3_per_day: float,
    constraints: Constraints,
    year: int,
    control_step: int,
    produced_water_by_step: Sequence[float],
) -> float:

    return injection_budget_for_step(
        control_step=control_step,
        constraints=constraints,
        year=year,
        produced_water_by_step=produced_water_by_step,
        physical_limit_m3_per_day=physical_limit_m3_per_day,
    ).limit_m3_per_day


def _active_outage_wells(
    constraints: Constraints, control_step: int
) -> frozenset[str]:
    return frozenset(
        outage.well
        for outage in constraints.well_outages
        if outage.control_step_from <= control_step <= outage.control_step_to
    )


def _outage_events(
    state: PolicyState, wells: frozenset[str]
) -> tuple[ControlEvent, ...]:
    events: list[ControlEvent] = []
    for well in sorted(wells):
        observation = state.wells.get(well)
        if observation is None:
            continue
        target_kind = (
            EventKind.SET_RATE
            if observation.role is Role.INJ
            else EventKind.SET_LRAT
        )
        events.extend(
            (
                ControlEvent(
                    control_step=state.control_step,
                    well=well,
                    kind=target_kind,
                    value=0.0,
                ),
                ControlEvent(
                    control_step=state.control_step,
                    well=well,
                    kind=EventKind.SHUT,
                ),
            )
        )
    return tuple(events)


def _baseline_injection_by_step(schedule: Schedule) -> tuple[dict[str, float], ...]:

    current: dict[str, float] = {
        well: (
            float(state.setpoint or 0.0)
            if state.operating_status is OperatingStatus.OPEN
            else 0.0
        )
        for well, state in schedule.initial_state.items()
    }
    by_step: dict[int, list[ControlEvent]] = {}
    for event in schedule.control_events:
        by_step.setdefault(event.control_step, []).append(event)

    dense: list[dict[str, float]] = []
    for step in range(schedule.meta.n_intervals):
        for event in by_step.get(step, ()):
            if event.kind is EventKind.SET_RATE:
                current[event.well] = float(event.value or 0.0)
            elif event.kind is EventKind.SHUT:
                current[event.well] = 0.0
        dense.append(dict(current))
    return tuple(dense)


def _baseline_conversion_steps(schedule: Schedule) -> dict[str, int]:

    steps: dict[str, int] = {}
    for event in schedule.control_events:
        if event.kind is EventKind.CONVERT_INJ:
            previous = steps.get(event.well)
            if previous is None or event.control_step < previous:
                steps[event.well] = event.control_step
    return steps


def _admit(
    pending: dict[tuple[int, str, EventKind], ControlEvent],
    event: ControlEvent,
    hard: HardConstraints,
    projection: Projection = project_to_hard_constraints,
) -> ControlEvent:

    admitted = projection(event, hard)
    pending[(admitted.control_step, admitted.well, admitted.kind)] = admitted
    return admitted


def _emit_dense_layer(
    pending: dict[tuple[int, str, EventKind], ControlEvent],
    step: int,
    state: PolicyState,
    *,
    current_role: dict[str, Role],
    current_is_open: dict[str, bool],
    current_setpoint: dict[str, float],
    hard: HardConstraints,
    projection: Projection = project_to_hard_constraints,
) -> None:

    for well in state.wells:
        role = current_role.get(well, Role.PROD)
        target_kind = EventKind.SET_RATE if role is Role.INJ else EventKind.SET_LRAT
        if (step, well, target_kind) not in pending:
            _admit(
                pending,
                ControlEvent(
                    control_step=step,
                    well=well,
                    kind=target_kind,
                    value=current_setpoint.get(well, 0.0),
                ),
                hard,
                projection,
            )
        status_kind = EventKind.OPEN if current_is_open.get(well, False) else EventKind.SHUT
        other = EventKind.SHUT if status_kind is EventKind.OPEN else EventKind.OPEN
        pending.pop((step, well, other), None)
        if (step, well, status_kind) not in pending:
            _admit(
                pending,
                ControlEvent(
                    control_step=step, well=well, kind=status_kind, value=None
                ),
                hard,
                projection,
            )


def _close_producing_side_on_conversion(
    pending: dict[tuple[int, str, EventKind], ControlEvent],
    step: int,
    decisions: Sequence[ControlEvent],
    hard: HardConstraints,
    projection: Projection = project_to_hard_constraints,
) -> None:

    converted = {
        event.well for event in decisions if event.kind is EventKind.CONVERT_INJ
    }
    for well in converted:
        key = (step, well, EventKind.SET_LRAT)
        event = pending.get(key)
        if event is not None and event.value:
            _admit(pending, replace(event, value=0.0), hard, projection)


def _scale_step_injection_to_limit(
    pending: dict[tuple[int, str, EventKind], ControlEvent],
    step: int,
    limit_m3_per_day: float,
    *,
    current_is_open: dict[str, bool],
    current_setpoint: dict[str, float],
    hard: HardConstraints = UNCONSTRAINED_WELLS,
    projection: Projection = project_to_hard_constraints,
) -> float:

    keys = [
        key
        for key in pending
        if key[0] == step and key[2] is EventKind.SET_RATE
    ]
    total = sum(float(pending[key].value or 0.0) for key in keys)
    if not math.isfinite(limit_m3_per_day) or total <= limit_m3_per_day + 1.0e-9:
        return total
    factor = 0.0 if total <= 0.0 else limit_m3_per_day / total
    for key in keys:
        event = pending[key]
        raw_value = float(event.value or 0.0) * factor
        value = (
            math.floor(raw_value / SETPOINT_STEP_M3_PER_DAY)
            * SETPOINT_STEP_M3_PER_DAY
        )
        _admit(pending, replace(event, value=value), hard, projection)
        current_setpoint[event.well] = value
        if value <= 0.0:
            current_is_open[event.well] = False
            pending.pop((step, event.well, EventKind.OPEN), None)
            _admit(
                pending,
                ControlEvent(
                    control_step=step,
                    well=event.well,
                    kind=EventKind.SHUT,
                ),
                hard,
                projection,
            )
    return sum(float(pending[key].value or 0.0) for key in keys)


DAMPER_STEP_FRACTION = 0.5


def _damped_value(prior: float, proposed: float) -> float:
    blended = prior + (proposed - prior) * DAMPER_STEP_FRACTION
    return math.floor(blended / SETPOINT_STEP_M3_PER_DAY) * SETPOINT_STEP_M3_PER_DAY


def _relax_rate_layer(
    previous: Schedule, proposed: Schedule, *, symmetric: bool = True
) -> Schedule:

    rate_kinds = (EventKind.SET_LRAT, EventKind.SET_RATE)
    previous_rates = {
        (event.control_step, event.well, event.kind): float(event.value or 0.0)
        for event in previous.control_events
        if event.kind in rate_kinds
    }
    relaxed_rates: dict[tuple[int, str], float] = {}
    events: list[ControlEvent] = []
    for event in proposed.control_events:
        if event.kind not in rate_kinds:
            events.append(event)
            continue
        value = float(event.value or 0.0)
        prior = previous_rates.get((event.control_step, event.well, event.kind))
        if prior is not None and value > 0.0:
            if event.kind is EventKind.SET_RATE and not symmetric:
                value = min(value, prior)
            else:
                value = _damped_value(prior, value)
        value = max(0.0, value)
        events.append(replace(event, value=value))
        relaxed_rates[(event.control_step, event.well)] = value

    normalized: list[ControlEvent] = []
    for event in events:
        if event.kind in (EventKind.OPEN, EventKind.SHUT):
            value = relaxed_rates.get((event.control_step, event.well))
            if value is not None:
                event = replace(
                    event,
                    kind=EventKind.OPEN if value > 0.0 else EventKind.SHUT,
                )
        normalized.append(event)
    return canonicalize(replace(proposed, control_events=tuple(normalized)))


def make_policy(
    env: SearchEnvironment,
    theta: Theta,
    trace_sink: dict,
    *,
    water_reference_response: ResponseArtifact | None = None,
    projection: Projection = project_to_hard_constraints,
    command_margin: float | None = None,
    symmetric_damper: bool = True,
):

    command_margin = (
        (
            WATER_COMMAND_SAFETY_FACTOR
            if water_supply_policy(env.constraints).enabled
            else 1.0
        )
        if command_margin is None
        else command_margin
    )
    wells = env.base_schedule.meta.wells
    commission_step = _commission_steps(env.base_schedule)
    flow_start_step = _flow_start_steps(
        env.base_schedule,
        _rates_at(env.real_history, _HISTORY_DECK_OFFSET),
    )
    role_at_commission = _role_at_commission(env.base_schedule)
    well_caps, field_limit = _physical_caps(env.base_schedule)
    hard_constraints = HardConstraints(well_cap_m3_per_day=well_caps)
    baseline_injection = _baseline_injection_by_step(env.base_schedule)
    baseline_conversion = _baseline_conversion_steps(env.base_schedule)
    commissioning_setpoint: dict[str, float] = {}
    for event in env.base_schedule.control_events:
        if event.kind in (EventKind.SET_RATE, EventKind.SET_LRAT) and event.value:
            key = (event.well, event.control_step)
            if event.control_step == commission_step.get(event.well, -1):
                commissioning_setpoint.setdefault(event.well, event.value)

    def policy(feedback: ResponseArtifact | PolicyFeedback) -> Schedule:
        previous_schedule: Schedule | None = None
        if isinstance(feedback, PolicyFeedback):
            response = feedback.response
            previous_schedule = feedback.schedule
        else:
            response = feedback
        current_role: dict[str, Role] = dict(role_at_commission)
        current_is_open: dict[str, bool] = {
            well: env.base_schedule.initial_state[well].operating_status.value == "OPEN"
            for well in wells
        }
        current_setpoint: dict[str, float] = {
            well: env.base_schedule.initial_state[well].setpoint for well in wells
        }
        context = RuleContext(
            normatives=env.normatives,
            oil_density_t_per_m3=env.oil_density_t_per_m3,
            constraints=env.constraints,
            influence=env.lambda_,
            groups=env.groups,
            memory=PolicyMemory(),
        )
        pending: dict[tuple[int, str, EventKind], ControlEvent] = {}
        trace_entries = []
        budget_entries: list[InjectionBudget] = []
        produced_water_by_step: list[float] = []
        for step in range(N_INTERVALS):
            for well, entry in flow_start_step.items():
                if entry == step and not current_is_open.get(well, False):
                    current_is_open[well] = True
                    if well in commissioning_setpoint:
                        current_setpoint[well] = commissioning_setpoint[well]
            state = _build_policy_state(
                step,
                response,
                wells=wells,
                current_role=current_role,
                current_is_open=current_is_open,
                current_setpoint=current_setpoint,
                commission_step=commission_step,
                oil_density_t_per_m3=env.oil_density_t_per_m3,
            )
            produced_water_by_step.append(
                _interval_produced_water_rate_m3_per_day(
                    water_reference_response or response,
                    step,
                    env.control_dates,
                    env.oil_density_t_per_m3,
                )
            )
            if not state.wells:
                continue
            budget = injection_budget_for_step(
                control_step=step,
                constraints=env.constraints,
                year=env.control_dates[step].year,
                produced_water_by_step=produced_water_by_step,
                physical_limit_m3_per_day=field_limit,
                command_margin=command_margin,
            )
            budget_entries.append(budget)
            step_field_limit = budget.limit_m3_per_day
            step_liquid_limit = liquid_limit_for_step(
                env.constraints, env.control_dates[step].year, step
            )
            injection, offtake = _group_injection_offtake(state, env.groups)
            result = run_step(
                state,
                replace(
                    context,
                    group_injection_m3_per_day=injection,
                    group_offtake_m3_per_day=offtake,
                    baseline_injection_m3_per_day=baseline_injection[step],
                    injection_cap_m3_per_day=well_caps,
                    baseline_conversion_step=baseline_conversion,
                ),
                theta,
                env.flags,
                field_limit_m3_per_day=step_field_limit,
                field_liquid_limit_m3_per_day=step_liquid_limit,
                setpoint_step_m3_per_day=SETPOINT_STEP_M3_PER_DAY,
            )
            trace_entries.extend(leveled.entry for leveled in result.trace.entries)
            outage_wells = _active_outage_wells(env.constraints, step)
            not_ready_wells = frozenset(
                well
                for well, entry in flow_start_step.items()
                if commission_step.get(well, entry) <= step < entry
            )
            blocked_wells = outage_wells | not_ready_wells
            decisions = tuple(
                event for event in result.decisions if event.well not in blocked_wells
            ) + _outage_events(state, blocked_wells)
            for event in decisions:
                event = _admit(pending, event, hard_constraints, projection)
                context = replace(
                    context,
                    memory=_apply_decision(
                        event,
                        current_role=current_role,
                        current_is_open=current_is_open,
                        current_setpoint=current_setpoint,
                        memory=context.memory,
                    ),
                )
            _close_producing_side_on_conversion(
                pending, step, decisions, hard_constraints, projection
            )
            _emit_dense_layer(
                pending,
                step,
                state,
                current_role=current_role,
                current_is_open=current_is_open,
                current_setpoint=current_setpoint,
                hard=hard_constraints,
                projection=projection,
            )
            commanded_injection = _scale_step_injection_to_limit(
                pending,
                step,
                step_field_limit,
                current_is_open=current_is_open,
                current_setpoint=current_setpoint,
                hard=hard_constraints,
                projection=projection,
            )
            if commanded_injection > step_field_limit + 1.0e-9:
                raise ScheduleSearchError(
                    f"control_step={step}: команда закачки {commanded_injection} "
                    f"м³/сут превышает потолок {step_field_limit} м³/сут, "
                    f"ограничение {budget.binding_source}"
                )
            context = replace(
                context,
                memory=_advance_memory(state, context, esp_catalog=env.normatives.esp_catalog),
            )
        trace_sink["trace"] = RunTrace(entries=tuple(trace_entries), flags=env.flags)
        trace_sink["injection_budget"] = tuple(
            entry.as_trace_entry() for entry in budget_entries
        )
        candidate = replace(
            env.base_schedule,
            control_events=tuple(pending.values()),
            meta=replace(env.base_schedule.meta, provenance="policy-search-candidate"),
        )
        candidate = canonicalize(candidate)
        return (
            candidate
            if previous_schedule is None
            else _relax_rate_layer(
                previous_schedule, candidate, symmetric=symmetric_damper
            )
        )

    return policy


def predict_economics(env: SearchEnvironment, model_input, response: ResponseArtifact) -> dict[str, float]:
    physical = analyze_base_case(
        response, env.deck_dates, env.t0_deck_date_index, env.normatives, env.policies,
    ).npv_methodology
    if env.npv_head is None:
        blended = env.npv_calibration.apply(physical) if env.npv_calibration is not None else physical
        return {"physical": physical, "blended": blended}
    _validate_npv_scoring_is_unambiguous(env.npv_head, env.npv_calibration)
    direct = env.npv_head.predict(model_input)
    weight = float(getattr(env.npv_head, "physical_npv_weight", 0.0))
    return {"direct": direct, "physical": physical, "blended": (1.0 - weight) * direct + weight * physical}


class MissingReferenceError(PhysicallyImpossibleScheduleError):

    SELF_REFERENCE = (
        "опора и кандидат — одно расписание: differential-инварианты сравнивают "
        "кандидата с опорой, при совпадении все разности тождественно нулевые и "
        "инвариант ничего не утверждает; он не нарушен, он не определён"
    )

    def __init__(self, reason: str) -> None:
        description = (
            "опора недоступна, дифференциальные инварианты не проверены: "
            f"{', '.join(_DIFFERENTIAL_INVARIANT_NAMES)}; {reason}"
        )
        super().__init__({}, description, _DIFFERENTIAL_INVARIANT_NAMES)


def full_physics_report(
    env: SearchEnvironment, schedule: Schedule, candidate: RawModelOutput
) -> PhysicsReport:
    if env.reference_schedule is None or env.reference_response is None:
        raise MissingReferenceError(
            "провенанс опоры: "
            + env.provenance.get("reference", "absent: опора не строилась")
        )
    single = check_prediction(
        candidate, schedule=schedule, oil_density_t_per_m3=env.oil_density_t_per_m3
    )
    if (
        candidate.canonical_schedule_hash
        == env.reference_response.canonical_schedule_hash
        and not getattr(env, "physics_gate", True)
    ):
        skipped = {
            name: reason
            for name, reason in single.skipped.items()
            if name not in _DIFFERENTIAL_INVARIANT_NAMES
        }
        skipped.update(
            {
                name: MissingReferenceError.SELF_REFERENCE
                for name in _DIFFERENTIAL_INVARIANT_NAMES
            }
        )
        return PhysicsReport(
            counts=dict(single.counts),
            examples=single.examples,
            evaluated=single.evaluated,
            skipped=skipped,
            n_nodes=single.n_nodes,
            n_wells=single.n_wells,
        )
    try:
        pair = check_pair(
            env.reference_response,
            candidate,
            reference_schedule=env.reference_schedule,
            candidate_schedule=schedule,
            lam=env.lambda_,
            oil_density_t_per_m3=env.oil_density_t_per_m3,
        )
    except PhysicsCheckError as error:
        raise MissingReferenceError(
            f"пара опора/кандидат непригодна для проверки: {error}"
        ) from error
    counts = dict(single.counts)
    for name, count in pair.counts.items():
        counts[name] = counts.get(name, 0) + count
    skipped = {
        name: reason
        for name, reason in single.skipped.items()
        if name not in _DIFFERENTIAL_INVARIANT_NAMES
    }
    skipped.update(pair.skipped)
    return PhysicsReport(
        counts=counts,
        examples=single.examples + pair.examples,
        evaluated=single.evaluated + pair.evaluated,
        skipped=skipped,
        n_nodes=single.n_nodes,
        n_wells=single.n_wells,
    )


SELF_REFERENCE_SKIP_REASON = MissingReferenceError.SELF_REFERENCE


def format_ood_worst(ood: OodScore) -> str | None:
    worst = ood.worst
    if worst is None:
        return None
    return f"{worst.feature}@{worst.well}:{worst.control_step}"


def physics_counters(report: PhysicsReport) -> dict[str, int]:
    counters = {name: int(count) for name, count in sorted(report.counts.items())}
    counters["blocking_count"] = int(report.blocking_count)
    counters["warning_count"] = int(report.warning_count)
    counters["complete"] = int(report.complete)
    counters["admissible"] = int(report.admissible)
    return counters


class EnsembleSpreadError(ScheduleSearchError):
    pass


def ensemble_members(
    model: TrajectorySurrogate | TrajectoryEnsemble,
) -> tuple[TrajectorySurrogate, ...]:
    members = getattr(model, "models", None)
    if members is None:
        return ()
    return tuple(members)


def _member_outputs(
    model: TrajectoryEnsemble, model_input
) -> tuple[RawModelOutput, ...]:
    members = ensemble_members(model)
    if len(members) < 2:
        raise EnsembleSpreadError(
            "разброс ансамбля считается по членам, а их меньше двух"
        )
    return tuple(member._predict_output(model_input) for member in members)


def _total_oil_mass(output: RawModelOutput) -> float:
    return math.fsum(node.oil_mass_delta for node in output.nodes)


def spread_bracket(
    outputs: Sequence[RawModelOutput],
) -> tuple[RawModelOutput, RawModelOutput]:
    if len(outputs) < 2:
        raise EnsembleSpreadError(
            "крайние члены ансамбля выбираются минимум из двух прогнозов"
        )
    ranked = sorted(outputs, key=_total_oil_mass)
    return ranked[0], ranked[-1]


def _npv_of_output(
    env: SearchEnvironment,
    adapter: ResponseAdapter,
    schedule: Schedule,
    model_input,
    output: RawModelOutput,
    tag: str,
) -> float:
    states, intervals = adapter.adapt(
        output, schedule, env.real_history, env.control_dates
    )
    identity = {
        "model_version": env.model.version,
        "schedule_hash": hash_schedule(schedule),
        "ensemble_member": tag,
    }
    response = ResponseArtifact(
        source_run_id=f"surrogate-member:{env.model.version[:12]}",
        response_hash=hashlib.sha256(canonical_bytes(identity)).hexdigest(),
        state_at_date=states,
        interval_response=intervals,
    )
    return float(predict_economics(env, model_input, response)["blended"])


def ensemble_npv_sigma(
    env: SearchEnvironment,
    adapter: ResponseAdapter,
    schedule: Schedule,
    model_input,
) -> float | None:
    if not isinstance(env.model, TrajectoryEnsemble):
        return None
    low_output, high_output = spread_bracket(_member_outputs(env.model, model_input))
    npv_low = _npv_of_output(
        env, adapter, schedule, model_input, low_output, "low"
    )
    npv_high = _npv_of_output(
        env, adapter, schedule, model_input, high_output, "high"
    )
    sigma = abs(npv_high - npv_low) / 2.0
    if not math.isfinite(sigma):
        raise EnsembleSpreadError(
            "разброс ЧДД по членам ансамбля не конечен: "
            f"npv_low={npv_low!r}, npv_high={npv_high!r}"
        )
    return sigma


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
