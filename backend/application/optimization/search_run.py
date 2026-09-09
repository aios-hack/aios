from __future__ import annotations

import hashlib
import json
import math
import os
import random
import sys
import time
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Mapping, Sequence

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from backend.core.contracts import (
    OptimizerResult,
    ScenarioViolation,
    Schedule,
    Theta,
    EventKind,
    compensation_policy,
    hash_schedule,
    canonical_bytes,
    water_supply_policy,
)
from backend.core.contracts.schedule import MAX_LRAT_M3_PER_DAY
from backend.core.contracts.constraints import Constraints, bhp_limits
from backend.domain.economics import load_response_artifact
from backend.application.optimization.schedule_search import (
    SOURCE_WATER_BALANCE_REPAIR,
    injection_budget_for_step,
    load_environment, make_evaluator, make_policy,
    OutOfDomainScheduleError, PhysicallyImpossibleScheduleError,
)
from backend.application.optimization.runtime_artifacts import (
    resolve_runtime_artifacts,
    validate_runtime_economic_head,
)
from backend.application.optimization.search import optimize
from backend.domain.policy.fixed_point import FixedPointResult, resolve
from backend.domain.policy.theta import default_theta
from backend.domain.schedule.case_limits import YearlyProduction, apply_case_limits
from backend.domain.schedule import (
    ViolationKind,
    canonicalize,
    validate_dynamic,
    validate_static,
)
from backend.domain.schedule.validate import Violation
from backend.domain.schedule.validate_dynamic import (
    FIRST_CONTROL_DECK_DATE_INDEX,
    year_of_step,
)
from backend.infrastructure.resources import chdd_python_dir, model_z_dir
from backend.application.cases import load_case
from backend.domain.configuration.constraints_io import constraints_hash

LAMBDA = Path(os.environ.get("AIOS_LAMBDA_PATH", "data/lambda-window-2007/lambda.json"))
RESPONSE = Path("data/base_case/response.json")
CONSTRAINTS = Path(
    os.environ.get("AIOS_CONSTRAINTS_PATH", "config/competition-constraints.json")
)
SEARCH_DIAGNOSTICS = Path(os.environ.get("AIOS_SEARCH_DIAGNOSTICS_PATH", "data/lambda-window-2007/cmaes-diagnostics.json"))
SEARCH_RESULT = Path(os.environ.get("AIOS_SEARCH_RESULT_PATH", "data/lambda-window-2007/cmaes.json"))
BASE_NPV = 11_873_122_324.91
SEED = 20260816


class SearchRunError(RuntimeError):
    pass


def _artifact_sha256(path: Path, name: str) -> str:
    try:
        raw = Path(path).read_bytes()
    except OSError as error:
        raise SearchRunError(
            f"провенанс поиска не собран: артефакт {name} по пути {path} "
            f"не читается — {error}"
        ) from error
    return hashlib.sha256(raw).hexdigest()


DEFAULT_SEARCH_CAP = 2
DEFAULT_FINAL_CAP = 8


def _positive_cap(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None:
        return default
    try:
        value = int(raw)
    except ValueError as error:
        raise SearchRunError(
            f"{name}={raw!r} — потолок неподвижной точки задаётся целым числом"
        ) from error
    if value <= 0:
        raise SearchRunError(
            f"{name}={value} не положителен: потолок неподвижной точки "
            f"берётся снаружи, но обязан допускать хотя бы одну итерацию"
        )
    return value


SEARCH_CAP = _positive_cap("AIOS_SEARCH_FIXED_POINT_CAP", DEFAULT_SEARCH_CAP)
FINAL_CAP = _positive_cap("AIOS_FINAL_FIXED_POINT_CAP", DEFAULT_FINAL_CAP)
FINALIST_CAP = 4
RISK_AVERSION_BETA = float(os.environ.get("AIOS_RISK_AVERSION_BETA", "0.0"))
OOD_CALIBRATION_FORMAT = "aios.ood-calibration.v1"
DEFAULT_OOD_CALIBRATION = "out/ood-calibration.json"
CONSERVATIVE_OOD_THRESHOLD = 0.0


@dataclass(frozen=True, slots=True)
class OodThreshold:

    value: float
    origin: str
    calibrated: bool
    source: str
    point_count: int
    detail: str

    def as_provenance(self) -> dict[str, str]:
        return {
            "ood_threshold": repr(self.value),
            "ood_threshold_origin": self.origin,
            "ood_threshold_calibrated": "true" if self.calibrated else "false",
            "ood_threshold_source": self.source,
            "ood_threshold_point_count": str(self.point_count),
            "ood_threshold_detail": self.detail,
        }


def _ood_threshold_decision(
    environ: Mapping[str, str] | None = None,
) -> OodThreshold:
    env = os.environ if environ is None else environ
    override = env.get("AIOS_OOD_THRESHOLD")
    configured = env.get("AIOS_OOD_CALIBRATION_PATH")
    root = env.get("AIOS_PROJECT_ROOT")
    calibration_path = (
        Path(configured)
        if configured
        else (Path(root) if root else Path.cwd()) / DEFAULT_OOD_CALIBRATION
    )
    if override is not None:
        try:
            value = float(override)
        except ValueError as error:
            raise SearchRunError(
                f"AIOS_OOD_THRESHOLD={override!r} — порог области применимости "
                "задаётся числом"
            ) from error
        if not math.isfinite(value) or value < 0.0:
            raise SearchRunError(
                f"AIOS_OOD_THRESHOLD={override!r} — порог обязан быть конечным "
                "и неотрицательным"
            )
        return OodThreshold(
            value=value,
            origin="environment-override",
            calibrated=False,
            source="none" if not calibration_path.is_file() else str(calibration_path),
            point_count=0,
            detail=(
                f"AIOS_OOD_THRESHOLD={override!r} перекрывает артефакт калибровки; "
                "происхождение порога — явное переопределение оператором"
            ),
        )
    if configured and not calibration_path.is_file():
        raise SearchRunError(
            f"AIOS_OOD_CALIBRATION_PATH={configured} указывает на отсутствующий "
            "артефакт калибровки"
        )
    if not calibration_path.is_file():
        return OodThreshold(
            value=CONSERVATIVE_OOD_THRESHOLD,
            origin="uncalibrated-conservative-default",
            calibrated=False,
            source="none",
            point_count=0,
            detail=(
                f"артефакт калибровки {calibration_path} отсутствует: порог "
                f"{CONSERVATIVE_OOD_THRESHOLD} взят как консервативный, "
                "НЕ ОТКАЛИБРОВАН — отвергается любой кандидат хоть с одним узлом "
                "вне обучающего диапазона"
            ),
        )
    try:
        payload = json.loads(calibration_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise SearchRunError(
            f"артефакт калибровки OOD {calibration_path} не читается: {error}"
        ) from error
    if not isinstance(payload, dict) or payload.get("format") != OOD_CALIBRATION_FORMAT:
        raise SearchRunError(
            f"неподдерживаемый артефакт калибровки OOD: {calibration_path}"
        )
    threshold = payload.get("threshold")
    if isinstance(threshold, bool) or not isinstance(threshold, (int, float)):
        raise SearchRunError(f"{calibration_path}: порог калибровки не число")
    value = float(threshold)
    if not math.isfinite(value) or value < 0.0:
        raise SearchRunError(
            f"{calibration_path}: порог калибровки {value} не конечен или отрицателен"
        )
    count = payload.get("point_count")
    if isinstance(count, bool) or not isinstance(count, int) or count < 1:
        raise SearchRunError(
            f"{calibration_path}: калибровка без единой измеренной точки "
            "не задаёт порог"
        )
    reliable = bool(payload.get("curve_is_reliable", False))
    return OodThreshold(
        value=value,
        origin=(
            "calibration-artifact"
            if reliable
            else "calibration-artifact/insufficient-points"
        ),
        calibrated=True,
        source=str(calibration_path),
        point_count=count,
        detail=(
            f"порог {value} взят из {calibration_path} по {count} измеренным "
            f"точкам «ошибка против OOD»"
            + ("" if reliable else "; точек мало, кривая ненадёжна")
        ),
    )


def _soft_penalty_enabled(environ: Mapping[str, str] | None = None) -> bool:
    env = os.environ if environ is None else environ
    raw = env.get("AIOS_OOD_SOFT_PENALTY")
    if raw is None:
        return False
    normalized = raw.strip().lower()
    if normalized in ("1", "true", "yes", "on"):
        return True
    if normalized in ("", "0", "false", "no", "off"):
        return False
    raise SearchRunError(
        f"AIOS_OOD_SOFT_PENALTY={raw!r} — включение мягкого штрафа задаётся "
        "булевым значением (1/0, true/false, yes/no, on/off)"
    )


def _soft_penalty_rate(environ: Mapping[str, str] | None = None) -> float:
    env = os.environ if environ is None else environ
    raw = env.get("AIOS_OOD_PENALTY_PER_UNIT", "1.0")
    try:
        value = float(raw)
    except ValueError as error:
        raise SearchRunError(
            f"AIOS_OOD_PENALTY_PER_UNIT={raw!r} — ставка мягкого штрафа задаётся числом"
        ) from error
    if not math.isfinite(value) or value <= 0.0:
        raise SearchRunError(
            f"AIOS_OOD_PENALTY_PER_UNIT={raw!r} — ставка обязана быть конечной "
            "и положительной"
        )
    return value
BUDGET = 120

MISSING_SIGMA = (
    "β задана, но модель не даёт разброса: нужен ансамбль"
)

WATER_REPAIR_MARGIN = 0.98
WATER_REPAIR_CEILING = 0.95

SURROGATE_NONBLOCKING_KINDS = frozenset(
    {
        ViolationKind.BHP_BELOW_PRODUCER_LIMIT,
        ViolationKind.BHP_ABOVE_INJECTOR_LIMIT,
    }
)

BHP_KINDS = SURROGATE_NONBLOCKING_KINDS
SURROGATE_METRICS_FORMAT = "aios.surrogate-metrics.v2"
DEFAULT_SURROGATE_METRICS = "out/surrogate-metrics.json"


class BhpToleranceError(SearchRunError):
    pass


@dataclass(frozen=True, slots=True)
class BhpTolerance:

    delta_bar: float | None
    origin: str
    source: str
    n_states: int
    detail: str

    @property
    def measured(self) -> bool:
        return self.delta_bar is not None

    def as_provenance(self) -> dict[str, str]:
        return {
            "bhp_gate_delta_bar": (
                "unmeasured" if self.delta_bar is None else repr(self.delta_bar)
            ),
            "bhp_gate_delta_origin": self.origin,
            "bhp_gate_delta_source": self.source,
            "bhp_gate_delta_states": str(self.n_states),
            "bhp_gate_agreement": (
                "same-definition-as-submission"
                if self.measured
                else "documented-difference-search-lets-bhp-through"
            ),
            "bhp_gate_detail": self.detail,
        }


def _bhp_tolerance_decision(
    environ: Mapping[str, str] | None = None,
) -> BhpTolerance:
    env = os.environ if environ is None else environ
    override = env.get("AIOS_BHP_GATE_DELTA_BAR")
    configured = env.get("AIOS_SURROGATE_METRICS_PATH")
    root = env.get("AIOS_PROJECT_ROOT")
    metrics_path = (
        Path(configured)
        if configured
        else (Path(root) if root else Path.cwd()) / DEFAULT_SURROGATE_METRICS
    )
    if override is not None:
        try:
            value = float(override)
        except ValueError as error:
            raise BhpToleranceError(
                f"AIOS_BHP_GATE_DELTA_BAR={override!r} — допуск канала BHP "
                "задаётся числом в барах"
            ) from error
        if not math.isfinite(value) or value < 0.0:
            raise BhpToleranceError(
                f"AIOS_BHP_GATE_DELTA_BAR={override!r} — допуск обязан быть "
                "конечным и неотрицательным"
            )
        return BhpTolerance(
            delta_bar=value,
            origin="environment-override",
            source=str(metrics_path) if metrics_path.is_file() else "none",
            n_states=0,
            detail=(
                f"AIOS_BHP_GATE_DELTA_BAR={override!r} перекрывает отчёт метрик; "
                "происхождение допуска — явное переопределение оператором"
            ),
        )
    if configured and not metrics_path.is_file():
        raise BhpToleranceError(
            f"AIOS_SURROGATE_METRICS_PATH={configured} указывает на отсутствующий "
            "отчёт метрик суррогата"
        )
    if not metrics_path.is_file():
        return BhpTolerance(
            delta_bar=None,
            origin="unmeasured-report-absent",
            source="none",
            n_states=0,
            detail=(
                f"отчёт метрик {metrics_path} не считался: P95 ошибки канала BHP "
                "не измерена, придумывать её нельзя. Прежнее поведение сохранено — "
                "поиск пропускает нарушения BHP, сдача их блокирует; различие "
                "гейтов задокументировано этой пометкой"
            ),
        )
    try:
        payload = json.loads(metrics_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise BhpToleranceError(
            f"отчёт метрик суррогата {metrics_path} не читается: {error}"
        ) from error
    if not isinstance(payload, dict) or payload.get("format") != SURROGATE_METRICS_FORMAT:
        raise BhpToleranceError(
            f"неподдерживаемый отчёт метрик суррогата: {metrics_path}"
        )
    manifold = payload.get("optimizer_manifold")
    channel = manifold.get("bhp_channel") if isinstance(manifold, dict) else None
    if not isinstance(channel, dict):
        raise BhpToleranceError(
            f"{metrics_path}: в отчёте нет optimizer_manifold.bhp_channel — "
            "допуск канала BHP выводить не из чего"
        )
    if "unavailable" in channel:
        return BhpTolerance(
            delta_bar=None,
            origin="unmeasured-no-opm-response",
            source=str(metrics_path),
            n_states=0,
            detail=(
                f"{metrics_path}: {channel['unavailable']}. Прежнее поведение "
                "сохранено — поиск пропускает нарушения BHP, сдача их блокирует; "
                "различие гейтов задокументировано этой пометкой"
            ),
        )
    raw = channel.get("bhp_error_bar_p95")
    if isinstance(raw, bool) or not isinstance(raw, (int, float)):
        raise BhpToleranceError(
            f"{metrics_path}: bhp_error_bar_p95 не число — допуск не выводится"
        )
    value = float(raw)
    if not math.isfinite(value) or value < 0.0:
        raise BhpToleranceError(
            f"{metrics_path}: bhp_error_bar_p95={value} не конечен или отрицателен"
        )
    states = channel.get("n_states")
    if isinstance(states, bool) or not isinstance(states, int) or states < 1:
        raise BhpToleranceError(
            f"{metrics_path}: канал BHP без единого измеренного состояния "
            "не задаёт допуск"
        )
    return BhpTolerance(
        delta_bar=value,
        origin="metrics-report-p95",
        source=str(metrics_path),
        n_states=states,
        detail=(
            f"δ={value} бар — P95 ошибки канала BHP по {states} состояниям из "
            f"{metrics_path}; кандидат отклоняется, когда предсказанное BHP "
            "выходит за предел больше чем на δ"
        ),
    )


def bhp_exceedance_bar(violation: Violation, constraints: Constraints) -> float:
    value = violation.value
    if value is None or not math.isfinite(float(value)):
        raise BhpToleranceError(
            f"нарушение {violation.kind.value} без измеренного забойного давления: "
            "выход за предел посчитать не по чему"
        )
    limits = bhp_limits(constraints)
    if violation.kind is ViolationKind.BHP_BELOW_PRODUCER_LIMIT:
        return max(0.0, float(limits.producer_min_bar) - float(value))
    if violation.kind is ViolationKind.BHP_ABOVE_INJECTOR_LIMIT:
        return max(0.0, float(value) - float(limits.injector_max_bar))
    raise BhpToleranceError(
        f"{violation.kind.value} — не нарушение канала BHP, допуск неприменим"
    )


def surrogate_blocking_violations(
    violations: Sequence[Violation],
    constraints: Constraints,
    tolerance: BhpTolerance,
) -> tuple[Violation, ...]:
    kept: list[Violation] = []
    for item in violations:
        if item.kind not in BHP_KINDS:
            kept.append(item)
            continue
        if not tolerance.measured:
            continue
        if bhp_exceedance_bar(item, constraints) > tolerance.delta_bar:
            kept.append(item)
    return tuple(kept)


@dataclass(frozen=True, slots=True)
class IncumbentRecord:

    sequence: int
    stage: str
    schedule_hash: str
    npv_predicted: float
    theta: dict[str, float]
    ood_score: float | None
    ood_worst: str | None
    static_violations: int
    dynamic_blocking_violations: int
    physics_admissible: bool
    self_consistent: bool
    ood_exceedances: tuple[dict[str, object], ...] = ()

    def as_dict(self) -> dict[str, object]:
        return {
            "sequence": self.sequence,
            "stage": self.stage,
            "schedule_hash": self.schedule_hash,
            "npv_predicted": self.npv_predicted,
            "theta": dict(self.theta),
            "ood_score": self.ood_score,
            "ood_worst": self.ood_worst,
            "ood_exceedances": [dict(item) for item in self.ood_exceedances],
            "static_violations": self.static_violations,
            "dynamic_blocking_violations": self.dynamic_blocking_violations,
            "physics_admissible": self.physics_admissible,
            "self_consistent": self.self_consistent,
        }


class IncumbentRegistry:

    def __init__(self) -> None:
        self._records: list[IncumbentRecord] = []

    def promote(
        self,
        *,
        stage: str,
        schedule_hash: str,
        npv_predicted: float,
        theta: Mapping[str, float],
        ood_score: float | None,
        ood_worst: str | None,
        static_violations: int,
        dynamic_blocking_violations: int,
        physics_admissible: bool,
        self_consistent: bool,
        ood_exceedances: Sequence[Mapping[str, object]] = (),
    ) -> IncumbentRecord:
        record = IncumbentRecord(
            sequence=len(self._records),
            stage=stage,
            schedule_hash=schedule_hash,
            npv_predicted=float(npv_predicted),
            theta={name: float(value) for name, value in theta.items()},
            ood_score=None if ood_score is None else float(ood_score),
            ood_worst=ood_worst,
            static_violations=int(static_violations),
            dynamic_blocking_violations=int(dynamic_blocking_violations),
            physics_admissible=bool(physics_admissible),
            self_consistent=bool(self_consistent),
            ood_exceedances=tuple(dict(item) for item in ood_exceedances),
        )
        self._records.append(record)
        return record

    @property
    def records(self) -> tuple[IncumbentRecord, ...]:
        return tuple(self._records)

    @property
    def current(self) -> IncumbentRecord | None:
        return self._records[-1] if self._records else None

    def as_list(self) -> list[dict[str, object]]:
        return [record.as_dict() for record in self._records]


def incumbent_gate_passed(
    *,
    static_violations: int,
    dynamic_blocking_violations: int,
    ood_score: float | None,
    ood_threshold: float,
    physics_admissible: bool,
    ood_soft_penalty: bool = False,
) -> bool:
    if static_violations > 0:
        return False
    if dynamic_blocking_violations > 0:
        return False
    if not physics_admissible:
        return False
    if ood_score is None:
        return False
    if ood_soft_penalty:
        return True
    return ood_score <= ood_threshold


def _physics_admissible(physics: Mapping[str, int]) -> bool:
    if not physics:
        return False
    return bool(physics.get("admissible", 0))


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
    diagnostics = json.loads(SEARCH_DIAGNOSTICS.read_text(encoding="utf-8"))
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


OPM_BUDGET_JOURNAL = "out/opm-budget.jsonl"


class OpmBudgetError(SearchRunError):
    pass


@dataclass(frozen=True, slots=True)
class RunBudget:

    wallclock_seconds: float
    surrogate_evaluations: int
    opm_runs: int
    opm_runs_source: str
    opm_wallclock_seconds: float | None

    def as_dict(self) -> dict[str, object]:
        return {
            "wallclock_seconds": self.wallclock_seconds,
            "surrogate_evaluations": self.surrogate_evaluations,
            "opm_runs": self.opm_runs,
            "opm_runs_source": self.opm_runs_source,
            "opm_wallclock_seconds": self.opm_wallclock_seconds,
        }

    def as_provenance(self) -> dict[str, str]:
        return {
            "run_wallclock_seconds": repr(self.wallclock_seconds),
            "run_surrogate_evaluations": str(self.surrogate_evaluations),
            "run_opm_runs": str(self.opm_runs),
            "run_opm_runs_source": self.opm_runs_source,
            "run_opm_wallclock_seconds": (
                "unrecorded"
                if self.opm_wallclock_seconds is None
                else repr(self.opm_wallclock_seconds)
            ),
        }


def _opm_budget_path(environ: Mapping[str, str] | None = None) -> Path:
    env = os.environ if environ is None else environ
    override = env.get("AIOS_OPM_BUDGET_JOURNAL")
    if override is not None and override.strip():
        return Path(override).expanduser()
    root = env.get("AIOS_PROJECT_ROOT")
    return (Path(root) if root else Path.cwd()) / OPM_BUDGET_JOURNAL


def read_opm_budget(
    path: Path, since_line: int = 0
) -> tuple[int, float | None, int]:
    if since_line < 0:
        raise OpmBudgetError(
            f"since_line={since_line} отрицателен: журнал бюджета OPM читается "
            "с начала или с записанной отметки"
        )
    if not path.is_file():
        return 0, None, since_line
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError as error:
        raise OpmBudgetError(
            f"журнал бюджета OPM {path} не читается: {error}"
        ) from error
    runs = 0
    seconds = 0.0
    measured = 0
    for number, raw in enumerate(lines):
        if number < since_line or not raw.strip():
            continue
        try:
            entry = json.loads(raw)
        except ValueError as error:
            raise OpmBudgetError(
                f"{path}, строка {number + 1}: запись журнала не разбирается — {error}"
            ) from error
        if not isinstance(entry, dict) or "run_id" not in entry:
            raise OpmBudgetError(
                f"{path}, строка {number + 1}: запись без run_id — прогон не опознан"
            )
        runs += 1
        wallclock = entry.get("wallclock_seconds")
        if isinstance(wallclock, (int, float)) and not isinstance(wallclock, bool):
            seconds += float(wallclock)
            measured += 1
    return runs, (seconds if measured else None), len(lines)


def _journal_line_count(path: Path) -> int:
    if not path.is_file():
        return 0
    try:
        return len(path.read_text(encoding="utf-8").splitlines())
    except OSError as error:
        raise OpmBudgetError(
            f"журнал бюджета OPM {path} не читается: {error}"
        ) from error


@dataclass(frozen=True, slots=True)
class SearchOutcome:

    schedule: Schedule
    theta: Theta
    predicted_npv: float
    schedule_hash: str
    provenance: dict[str, str]
    evaluations: int
    converged: bool
    self_consistent: bool
    static_violations: int | None = None
    dynamic_blocking_violations: int | None = None
    incumbent_history: tuple[IncumbentRecord, ...] = ()
    budget: RunBudget | None = None


def _repair_predicted_water_balance(
    env,
    evaluator,
    schedule: Schedule,
    rounds: int = 8,
    budget_trace: list[dict[str, object]] | None = None,
):

    policy = water_supply_policy(env.constraints)
    if not policy.enabled:
        evaluated = evaluator(schedule)
        response = evaluated.state.response
        dynamic = validate_dynamic(
            schedule,
            response.state_at_date,
            response.interval_response,
            env.constraints,
            env.oil_density_t_per_m3,
            groups=env.groups,
        )
        return schedule, evaluated, dynamic, 0

    current = schedule
    for round_index in range(rounds + 1):
        evaluated = evaluator(current)
        response = evaluated.state.response
        dynamic = validate_dynamic(
            current,
            response.state_at_date,
            response.interval_response,
            env.constraints,
            env.oil_density_t_per_m3,
            groups=env.groups,
        )
        bad_steps = {
            item.control_step
            for item in dynamic.violations
            if item.kind is ViolationKind.WATER_SUPPLY_LIMIT_EXCEEDED
            and item.control_step is not None
        }
        if not bad_steps or round_index == rounds:
            return current, evaluated, dynamic, round_index

        produced_water: dict[int, float] = {}
        injected: dict[int, float] = {}
        for item in response.interval_response:
            oil_volume = max(0.0, item.oil_mass_delta) / env.oil_density_t_per_m3
            produced_water[item.control_step] = produced_water.get(item.control_step, 0.0) + max(
                0.0, item.liquid_volume_delta - oil_volume
            )
            injected[item.control_step] = injected.get(item.control_step, 0.0) + max(
                0.0, item.injection_volume_delta
            )
        factors: dict[int, float] = {}
        for step in bad_steps:
            source_step = step - policy.lag_steps
            days = (env.control_dates[step + 1] - env.control_dates[step]).days
            available = (
                policy.external_water_m3_per_day * days
                + float(policy.reinjection_fraction or 0.0)
                * produced_water.get(source_step, 0.0)
            )
            actual = injected.get(step, 0.0)
            factors[step] = (
                0.0
                if actual <= 0.0
                else min(
                    WATER_REPAIR_CEILING, WATER_REPAIR_MARGIN * available / actual
                )
            )
            if budget_trace is not None:
                budget_trace.append(
                    {
                        "control_step": step,
                        "round": round_index,
                        "binding_source": SOURCE_WATER_BALANCE_REPAIR,
                        "limit_m3": available * WATER_REPAIR_MARGIN,
                        "contributions": {
                            "available_m3": available,
                            "commanded_m3": actual,
                            "repair_margin": WATER_REPAIR_MARGIN,
                            "repair_ceiling": WATER_REPAIR_CEILING,
                            "factor": factors[step],
                        },
                    }
                )

        values: dict[tuple[int, str], float] = {}
        repaired = []
        for event in current.control_events:
            if event.kind is EventKind.SET_RATE and event.control_step in factors:
                value = math.floor(float(event.value or 0.0) * factors[event.control_step])
                event = replace(event, value=max(0.0, value))
                values[(event.control_step, event.well)] = float(event.value or 0.0)
            repaired.append(event)
        normalized = []
        for event in repaired:
            value = values.get((event.control_step, event.well))
            if value is not None and event.kind in (EventKind.OPEN, EventKind.SHUT):
                event = replace(
                    event,
                    kind=EventKind.OPEN if value > 0.0 else EventKind.SHUT,
                )
            normalized.append(event)
        current = canonicalize(replace(current, control_events=tuple(normalized)))
    raise AssertionError("unreachable")


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
                f"коридор кейса несовместим с границами {name}: {bounds[name]}"
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
    rng = random.Random(SEED)
    baseline = apply_case_limits(
        env.base_schedule,
        env.constraints,
        env.control_dates,
        _peak_step_production(env, evaluator),
    )
    candidates = [baseline]
    wells = sorted({event.well for event in baseline.control_events
                    if event.kind in (EventKind.SET_LRAT, EventKind.SET_RATE) and event.value})
    for index in range(budget - 1):
        well = wells[index % len(wells)] if index < len(wells) else rng.choice(wells)
        direction = -1 if index % 2 == 0 else 1
        events = tuple(
            replace(event, value=max(0.0, min(MAX_LRAT_M3_PER_DAY if event.kind is EventKind.SET_LRAT else float('inf'),
                float(event.value) + direction * (1.0 if event.kind is EventKind.SET_LRAT else 5.0))))
            if event.well == well and event.kind in (EventKind.SET_LRAT, EventKind.SET_RATE)
               and event.value and event.value > (1 if event.kind is EventKind.SET_LRAT else 5)
            else event for event in baseline.control_events)
        candidates.append(canonicalize(replace(baseline, control_events=events)))
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
                                   'what': f'Нарушений условий плана: {len(static.violations)}'})
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
                                       'what': f'Нарушений ограничений: {len(blocking) + len(static.violations)}'})
                elif not admissible:
                    violations.append({'scenario_id': 'surrogate-physics', 'regret': 1,
                                       'what': 'Физическая проверка не пройдена или неполна.'})
                elif ood_score is None or (
                    not env.ood_soft_penalty and ood_score > env.ood_threshold
                ):
                    violations.append({'scenario_id': 'surrogate-domain', 'regret': 1,
                                       'what': 'План вне области обучения.'})
                else:
                    npv = evaluated.npv
                    accepted.append((npv, schedule, index, static_count, blocking_count))
                    best = registry.current
                    if best is None or npv > best.npv_predicted:
                        registry.promote(
                            stage='baseline-neighborhood',
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
                strategy='baseline-neighborhood',
                ood_exceedances=ood_exceedances,
            )
        )
        print(f'локальный вариант {index + 1}/{budget}: допустим={not violations}, ЧДД={npv}', flush=True)
    diagnostics = json.loads(SEARCH_DIAGNOSTICS.read_text(encoding='utf-8'))
    diagnostics['fallback_budget'] = budget
    diagnostics['evaluations'].extend(records)
    diagnostics['incumbents'] = registry.as_list()
    SEARCH_DIAGNOSTICS.write_text(
        json.dumps(diagnostics, ensure_ascii=False, indent=2, allow_nan=False),
        encoding='utf-8',
    )
    if not accepted:
        raise SearchRunError('Ни политика, ни локальные изменения исходного плана не прошли проверки условий и области обучения.')
    npv, schedule, index, static_count, blocking_count = max(accepted, key=lambda item: item[0])
    provenance = dict(provenance, search_strategy='baseline-neighborhood',
                      selected_candidate='baseline' if index == 0 else 'local-change',
                      policy_equilibrium='not-claimed',
                      **tolerance.as_provenance())
    run_budget = close_run_clock(len(diagnostics['evaluations']))
    provenance = dict(provenance, **run_budget.as_provenance())
    return SearchOutcome(schedule, default_theta(), npv, hash_schedule(schedule), provenance,
                         len(diagnostics['evaluations']), False, False,
                         static_count, blocking_count, registry.records, run_budget)


def _risk_adjusted_npv(npv: float, sigma: float | None, beta: float) -> float:
    if beta <= 0.0:
        return float(npv)
    if sigma is None:
        raise SearchRunError(MISSING_SIGMA)
    return float(npv) - beta * float(sigma)


def select_finalist(finalists: Sequence[tuple], beta: float = RISK_AVERSION_BETA):
    if not finalists:
        raise SearchRunError(
            "отбор финалистов вызван на пустом наборе: выбирать не из чего"
        )
    if beta < 0.0:
        raise SearchRunError(
            f"коэффициент неприятия риска β={beta} отрицателен: штраф за "
            f"разброс не может быть премией"
        )
    if beta > 0.0 and any(item[7] is None for item in finalists):
        raise SearchRunError(MISSING_SIGMA)
    return max(
        finalists,
        key=lambda item: (
            item[3].self_consistent,
            _risk_adjusted_npv(item[0], item[7], beta),
        ),
    )


RUN_CLOCK: dict[str, object] = {"journal": None, "mark": 0, "started": None}


def start_run_clock() -> None:
    journal = _opm_budget_path()
    RUN_CLOCK["journal"] = journal
    RUN_CLOCK["mark"] = _journal_line_count(journal)
    RUN_CLOCK["started"] = time.monotonic()


def close_run_clock(evaluations: int) -> RunBudget:
    journal = RUN_CLOCK["journal"]
    started = RUN_CLOCK["started"]
    if journal is None or started is None:
        raise OpmBudgetError(
            "учёт бюджета прогона не начат: измерить время и число прогонов OPM "
            "не по чему — вызовите start_run_clock перед поиском"
        )
    return measure_run_budget(
        journal, int(RUN_CLOCK["mark"]), time.monotonic() - started, evaluations
    )


def measure_run_budget(
    journal: Path, mark: int, wallclock: float, evaluations: int
) -> RunBudget:
    opm_runs, opm_seconds, _ = read_opm_budget(journal, mark)
    return RunBudget(
        wallclock_seconds=float(wallclock),
        surrogate_evaluations=int(evaluations),
        opm_runs=int(opm_runs),
        opm_runs_source=str(journal),
        opm_wallclock_seconds=None if opm_seconds is None else float(opm_seconds),
    )


def run_search(
    *,
    budget: int = BUDGET,
    case_path: Path | None = None,
    search_cap: int = SEARCH_CAP,
    final_cap: int = FINAL_CAP,
) -> SearchOutcome:
    if search_cap <= 0 or final_cap <= 0:
        raise SearchRunError(
            f"потолок неподвижной точки должен быть положительным: "
            f"поиск {search_cap}, финал {final_cap}"
        )
    start_run_clock()
    artifacts = resolve_runtime_artifacts()
    if artifacts.scenario_ood is None:
        raise SearchRunError("production search requires a versioned scenario OOD artifact")
    constraints_path = Path(case_path) if case_path is not None else CONSTRAINTS
    constraints = load_case(constraints_path)
    threshold_decision = _ood_threshold_decision()
    bhp_tolerance = _bhp_tolerance_decision()
    soft_penalty = _soft_penalty_enabled()
    penalty_rate = _soft_penalty_rate() if soft_penalty else 0.0
    env = load_environment(
        model_dir=model_z_dir(),
        normatives_path=chdd_python_dir() / "input" / "Нормативы_ЧДД.xlsx",
        response_path=RESPONSE,
        checkpoint_path=artifacts.checkpoint,
        feature_context_path=artifacts.feature_context,
        npv_head_path=artifacts.npv_head,
        npv_calibration_path=artifacts.npv_calibration,
        scenario_ood_path=artifacts.scenario_ood,
        lambda_path=LAMBDA,
        constraints=constraints,
        ood_threshold=threshold_decision.value,
        ood_soft_penalty=soft_penalty,
        ood_penalty_per_unit=penalty_rate,
    )
    validate_runtime_economic_head(artifacts, env.npv_head)
    initial = load_response_artifact(RESPONSE)
    evaluator = make_evaluator(env)
    final_evaluator = (
        make_evaluator(env, with_sigma=True)
        if RISK_AVERSION_BETA > 0.0
        else evaluator
    )
    search_start = _search_theta(constraints)
    provenance = {
        "model_version": env.model.version,
        "lambda_window": f"{env.lambda_.window_start}..{env.lambda_.window_end}",
        "lambda_stability": f"{env.lambda_.stability:.3f}",
        "seed": str(SEED),
        "runtime_artifact_source": artifacts.source,
        "feature_context_sha256": _artifact_sha256(
            artifacts.feature_context, "feature_context"
        ),
        "constraints_hash": constraints_hash(constraints),
        "scenario_ood_version": env.scenario_ood.version if env.scenario_ood else "none",
        "npv_head_version": env.npv_head.version if env.npv_head else "none",
        "constraints_path": str(constraints_path),
        **threshold_decision.as_provenance(),
        **bhp_tolerance.as_provenance(),
        "ood_soft_penalty": "true" if soft_penalty else "false",
        "ood_penalty_per_unit": repr(penalty_rate),
        "search_fixed_point_cap": str(search_cap),
        "final_fixed_point_cap": str(final_cap),
        "search_strategy": "cma-es",
        "policy_equilibrium": "not-claimed",
    }
    calls = {"n": 0, "best": float("-inf")}
    cards: list[dict[str, object]] = []
    registry = IncumbentRegistry()
    scenario_ood_threshold = (
        float(env.scenario_ood.threshold) if env.scenario_ood is not None else None
    )

    def objective(theta) -> OptimizerResult:
        try:
            result = resolve(make_policy(env, theta, {}), evaluator, initial, search_cap)
        except (OutOfDomainScheduleError, PhysicallyImpossibleScheduleError) as error:
            calls["n"] += 1
            rejection = {
                "scenario_id": "surrogate-rejected",
                "regret": 1.0,
                "what": str(error),
            }
            cards.append(
                candidate_card(
                    schedule_hash="",
                    theta=dict(theta.values),
                    npv_predicted=None,
                    npv_parts={},
                    ood_score=getattr(error, "score", None),
                    ood_worst=None,
                    scenario_ood=scenario_ood_threshold,
                    physics=getattr(error, "counts", {}) or {},
                    static_violations=None,
                    dynamic_blocking_violations=None,
                    feasible=False,
                    violations=[rejection],
                    strategy="cma-es",
                    ood_exceedances=getattr(error, "exceedances", ()) or (),
                )
            )
            return OptimizerResult(
                objective=-math.inf, feasible=False,
                violations_by_scenario=(ScenarioViolation(
                    scenario_id="surrogate-rejected", regret=1.0, what=str(error),
                ),), provenance=provenance,
            )
        npv = result.npv
        static = validate_static(result.schedule, env.constraints)
        violations: list[ScenarioViolation] = []
        if static.violations:
            violations.append(
                ScenarioViolation(
                    scenario_id="static-contract",
                    regret=float(len(static.violations)),
                    what=f"{len(static.violations)} нарушений статического контракта",
                )
            )
        if result.ood_score is None or (
            not soft_penalty and result.ood_score > env.ood_threshold
        ):
            score = result.ood_score
            excess = (
                1.0
                if score is None
                else max(0.0, float(score) - env.ood_threshold)
            )
            violations.append(
                ScenarioViolation(
                    scenario_id="surrogate-domain",
                    regret=excess,
                    what=(
                        "OOD score не вычислен"
                        if score is None
                        else f"OOD score {score:.6g} > {env.ood_threshold:.6g}"
                    ),
                )
            )
        calls["n"] += 1
        cards.append(
            candidate_card(
                schedule_hash=result.schedule_hash,
                theta=dict(theta.values),
                npv_predicted=npv if math.isfinite(npv) else None,
                npv_parts=result.npv_parts,
                ood_score=result.ood_score,
                ood_worst=result.ood_worst,
                scenario_ood=scenario_ood_threshold,
                physics=result.physics,
                static_violations=len(static.violations),
                dynamic_blocking_violations=None,
                feasible=not violations,
                violations=[
                    {
                        "scenario_id": item.scenario_id,
                        "regret": item.regret,
                        "what": item.what,
                    }
                    for item in violations
                ],
                strategy="cma-es",
                ood_exceedances=getattr(evaluator, "ood_exceedances", ()) or (),
            )
        )
        if npv > calls["best"]:
            calls["best"] = npv
            print(
                f"  оценка {calls['n']:3d}: новый максимум {npv / 1e9:.3f} млрд",
                flush=True,
            )
        return OptimizerResult(
            objective=npv,
            feasible=not violations,
            violations_by_scenario=tuple(violations),
            provenance=provenance,
        )

    print(
        f"CMA-ES: параметров 10, бюджет {budget} оценок, потолок неподвижной "
        f"точки в поиске {search_cap}, seed {SEED}",
        flush=True,
    )
    started = time.monotonic()
    report = optimize(
        objective, search_start, seed=SEED, max_evaluations=budget
    )
    elapsed = time.monotonic() - started
    print(
        f"поиск закончен за {elapsed / 60:.1f} мин, оценок {report.evaluations}, "
        f"поколений {report.generations}, останов: {report.stop_reason}, "
        f"допустимых найдено: {report.feasible_found}",
        flush=True,
    )
    SEARCH_DIAGNOSTICS.parent.mkdir(parents=True, exist_ok=True)
    SEARCH_DIAGNOSTICS.write_text(
        json.dumps(
            {
                "seed": SEED,
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
                "evaluations": _evaluation_cards(report.history, cards),
                "incumbents": registry.as_list(),
            },
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        ),
        encoding="utf-8",
    )

    ranked = sorted(
        report.feasible_history,
        key=lambda item: item.result.objective,
        reverse=True,
    )
    if not ranked:
        return _search_near_baseline(env, evaluator, budget, provenance, registry)

    finalists = []
    finalist_cards: list[dict[str, object]] = []
    seen: set[tuple[tuple[str, float], ...]] = set()
    print("\nполный пересчёт лучших допустимых θ:", flush=True)
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
            print(f"  finalist rejected: {error}", flush=True)
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
        print(
            f"  ЧДД {final.npv / 1e9:8.3f} млрд, итераций {final.iterations:2d}, "
            f"self-consistent={final.self_consistent}, OOD={evaluated.ood_score}, "
            f"water-repair={repair_rounds}, static={len(check.violations)}, "
            f"dynamic-blocking={len(surrogate_blocking)}, "
            f"physics-admissible={admissible}, "
            f"BHP-to-OPM={len(dynamic.blocking_violations) - len(surrogate_blocking)}",
            flush=True,
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
    _write_diagnostics_tail(finalist_cards, registry)
    if not finalists:
        return _search_near_baseline(env, evaluator, budget, provenance, registry)

    (
        predicted_npv,
        best_theta,
        schedule,
        final,
        check,
        surrogate_blocking,
        schedule_hash,
        predicted_sigma,
    ) = select_finalist(finalists, RISK_AVERSION_BETA)
    delta = 100.0 * (predicted_npv - BASE_NPV) / BASE_NPV
    print(
        f"\nθ*: ЧДД {predicted_npv / 1e9:.3f} млрд ({delta:+.1f}% к базовому), "
        f"нарушений validate_static: {len(check.violations)}, "
        f"блокирующих surrogate validate_dynamic: {len(surrogate_blocking)}, "
        f"событий {check.n_control_events}, "
        f"сошлось: {final.converged}, самосогласовано: {final.self_consistent}",
        flush=True,
    )
    print(f"canonical_schedule_hash: {schedule_hash}", flush=True)

    run_budget = close_run_clock(report.evaluations)
    return SearchOutcome(
        schedule=schedule,
        theta=best_theta,
        predicted_npv=predicted_npv,
        schedule_hash=schedule_hash,
        provenance=dict(
            provenance,
            search_strategy="cma-es",
            selected_candidate="finalist",
            risk_aversion_beta=str(RISK_AVERSION_BETA),
            npv_sigma=(
                "none" if predicted_sigma is None else repr(float(predicted_sigma))
            ),
            policy_equilibrium=(
                "reached" if final.self_consistent else "not-claimed"
            ),
            **run_budget.as_provenance(),
        ),
        evaluations=report.evaluations,
        converged=final.converged,
        self_consistent=final.self_consistent,
        static_violations=len(check.violations),
        dynamic_blocking_violations=len(surrogate_blocking),
        incumbent_history=registry.records,
        budget=run_budget,
    )


def main() -> int:
    budget = int(sys.argv[1]) if len(sys.argv) > 1 else BUDGET
    case_path = Path(sys.argv[2]) if len(sys.argv) > 2 else None
    outcome = run_search(budget=budget, case_path=case_path)
    out = SEARCH_RESULT
    schedule_path = out.with_name('cmaes-schedule.json')
    schedule_path.parent.mkdir(parents=True, exist_ok=True)
    schedule_path.write_bytes(canonical_bytes(outcome.schedule))
    out.write_text(
        json.dumps(
            {
                "seed": SEED,
                "schedule_path": str(schedule_path),
                "budget": budget,
                "evaluations": outcome.evaluations,
                "search_cap": int(
                    outcome.provenance.get("search_fixed_point_cap", SEARCH_CAP)
                ),
                "final_cap": int(
                    outcome.provenance.get("final_fixed_point_cap", FINAL_CAP)
                ),
                "theta": dict(outcome.theta.values),
                "npv_predicted": outcome.predicted_npv,
                "npv_baseline": BASE_NPV,
                "canonical_schedule_hash": outcome.schedule_hash,
                "static_violations": outcome.static_violations,
                "dynamic_blocking_violations": outcome.dynamic_blocking_violations,
                "converged": outcome.converged,
                "self_consistent": outcome.self_consistent,
                "incumbents": [
                    record.as_dict() for record in outcome.incumbent_history
                ],
                **(
                    {
                        "wallclock_seconds": None,
                        "surrogate_evaluations": None,
                        "opm_runs": None,
                        "opm_runs_source": None,
                        "opm_wallclock_seconds": None,
                    }
                    if getattr(outcome, "budget", None) is None
                    else outcome.budget.as_dict()
                ),
                "provenance": outcome.provenance,
            },
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    print(f"итог записан: {out}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
