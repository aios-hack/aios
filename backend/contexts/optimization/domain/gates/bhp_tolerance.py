from __future__ import annotations

from backend.contexts.optimization.domain.errors import (
    BhpToleranceError,
)
import json
import math
import os
from dataclasses import (
    dataclass,
)
from pathlib import Path
from typing import Mapping, Sequence
from backend.contexts.constraints.domain.constraints import Constraints, bhp_limits
from backend.domain.schedule import (
    ViolationKind,
)
from backend.contexts.schedule.domain.validate import Violation


SURROGATE_NONBLOCKING_KINDS = frozenset(
    {
        ViolationKind.BHP_BELOW_PRODUCER_LIMIT,
        ViolationKind.BHP_ABOVE_INJECTOR_LIMIT,
    }
)


BHP_KINDS = SURROGATE_NONBLOCKING_KINDS


SURROGATE_METRICS_FORMAT = "aios.surrogate-metrics.v2"


DEFAULT_SURROGATE_METRICS = "out/surrogate-metrics.json"


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


__all__ = [
    "BHP_KINDS",
    "BhpTolerance",
    "DEFAULT_SURROGATE_METRICS",
    "SURROGATE_METRICS_FORMAT",
    "SURROGATE_NONBLOCKING_KINDS",
    "bhp_exceedance_bar",
    "surrogate_blocking_violations",
]
