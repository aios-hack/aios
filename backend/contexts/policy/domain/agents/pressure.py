from __future__ import annotations

from dataclasses import dataclass

from backend.core.contracts import EventKind, Role, Rule, TraceEntry

from backend.contexts.policy.domain.agents.base import Bound, BoundSense, Proposal
from backend.contexts.policy.domain.levels import Level, LeveledTraceEntry
from backend.contexts.policy.domain.state import PolicyState, RuleContext

PRESSURE_AGENT = "PressureAgent"
PRESSURE_AGENT_RANK = 20
PRESSURE_CEILING_DECISION = "SET_PRESSURE_CEILING"

APPROACH_FRACTION = 0.10
RELIEF_FRACTION = 0.50

SIDE_CEILING = 1.0
SIDE_FLOOR = -1.0


@dataclass(frozen=True, slots=True)
class PressureCorridor:
    value_bar: float
    floor_bar: float | None
    ceiling_bar: float | None
    approach_fraction: float

    def __post_init__(self) -> None:
        if self.value_bar <= 0.0:
            raise ValueError(
                f"пластовое давление {self.value_bar} бар неположительно: "
                f"расстояние до предела не вычислимо"
            )
        if not 0.0 < self.approach_fraction <= 1.0:
            raise ValueError(
                f"доля коридора для порога приближения должна лежать в "
                f"(0, 1], получено {self.approach_fraction}"
            )
        if self.floor_bar is None and self.ceiling_bar is None:
            raise ValueError(
                "коридор пластового давления без единого предела: "
                "приближаться не к чему"
            )
        if (
            self.floor_bar is not None
            and self.ceiling_bar is not None
            and self.ceiling_bar <= self.floor_bar
        ):
            raise ValueError(
                f"потолок пластового давления {self.ceiling_bar} бар не выше "
                f"пола {self.floor_bar} бар: коридор пуст"
            )

    def width_bar(self) -> float:
        if self.floor_bar is not None and self.ceiling_bar is not None:
            return self.ceiling_bar - self.floor_bar
        known = self.floor_bar if self.ceiling_bar is None else self.ceiling_bar
        if known is None:
            raise ValueError(
                "ширина коридора пластового давления не определена: "
                "ни один предел не задан"
            )
        return known

    def margin_bar(self) -> float:
        return self.width_bar() * self.approach_fraction

    def ceiling_headroom_bar(self) -> float | None:
        if self.ceiling_bar is None:
            return None
        return self.ceiling_bar - self.value_bar

    def floor_headroom_bar(self) -> float | None:
        if self.floor_bar is None:
            return None
        return self.value_bar - self.floor_bar

    def near_ceiling(self) -> bool:
        headroom = self.ceiling_headroom_bar()
        return headroom is not None and headroom <= self.margin_bar()

    def near_floor(self) -> bool:
        headroom = self.floor_headroom_bar()
        return headroom is not None and headroom <= self.margin_bar()

    def relief_factor(self, headroom_bar: float) -> float:
        margin = self.margin_bar()
        if margin <= 0.0:
            raise ValueError(
                "порог приближения к пределу давления нулевой: "
                "во сколько раз снижать уставку — не определено"
            )
        share = max(0.0, min(1.0, headroom_bar / margin))
        return RELIEF_FRACTION + (1.0 - RELIEF_FRACTION) * share


@dataclass(frozen=True, slots=True)
class PressureRestriction:
    well: str
    kind: EventKind
    value_m3_per_day: float
    pressure_bar: float
    limit_bar: float
    headroom_bar: float
    margin_bar: float

    def __post_init__(self) -> None:
        if self.value_m3_per_day < 0.0:
            raise ValueError(
                f"{self.well}: потолок по пластовому давлению отрицателен "
                f"({self.value_m3_per_day} м³/сут) — ограничение "
                f"не интерпретируемо"
            )

    def side(self) -> float:
        return SIDE_CEILING if self.kind is EventKind.SET_RATE else SIDE_FLOOR

    def as_bound(self) -> Bound:
        return Bound(
            well=self.well,
            kind=self.kind,
            sense=BoundSense.CEILING,
            value=self.value_m3_per_day,
        )

    def as_inputs(self) -> dict[str, float]:
        return {
            "pressure_ceiling_m3_per_day": self.value_m3_per_day,
            "field_pressure_bar": self.pressure_bar,
            "pressure_limit_bar": self.limit_bar,
            "headroom_bar": self.headroom_bar,
            "approach_margin_bar": self.margin_bar,
            "limit_side": self.side(),
        }


def pressure_corridor_of(context: RuleContext) -> PressureCorridor | None:
    value = context.field_pressure_bar
    if value is None:
        return None
    if context.pressure_floor_bar is None and context.pressure_ceiling_bar is None:
        return None
    return PressureCorridor(
        value_bar=float(value),
        floor_bar=(
            None
            if context.pressure_floor_bar is None
            else float(context.pressure_floor_bar)
        ),
        ceiling_bar=(
            None
            if context.pressure_ceiling_bar is None
            else float(context.pressure_ceiling_bar)
        ),
        approach_fraction=APPROACH_FRACTION,
    )


def restriction_for(
    corridor: PressureCorridor,
    well: str,
    role: Role,
    setpoint_m3_per_day: float,
) -> PressureRestriction | None:
    if setpoint_m3_per_day <= 0.0:
        return None
    if role is Role.INJ:
        if not corridor.near_ceiling():
            return None
        headroom = corridor.ceiling_headroom_bar()
        limit = corridor.ceiling_bar
        kind = EventKind.SET_RATE
    else:
        if not corridor.near_floor():
            return None
        headroom = corridor.floor_headroom_bar()
        limit = corridor.floor_bar
        kind = EventKind.SET_LRAT
    if headroom is None or limit is None:
        raise ValueError(
            f"{well}: предел пластового давления объявлен приближенным, "
            f"но само значение предела не задано — во что упирается уставка, "
            f"назвать нечем"
        )
    return PressureRestriction(
        well=well,
        kind=kind,
        value_m3_per_day=setpoint_m3_per_day * corridor.relief_factor(headroom),
        pressure_bar=corridor.value_bar,
        limit_bar=limit,
        headroom_bar=headroom,
        margin_bar=corridor.margin_bar(),
    )


@dataclass(frozen=True, slots=True)
class PressureAgent:
    name: str = PRESSURE_AGENT
    level: Level = Level.FIELD
    rank: int = PRESSURE_AGENT_RANK
    responsibilities: tuple[str, ...] = (
        "снижает закачку при подходе среднего пластового давления к потолку "
        "кейса и отбор при подходе к полу, выставляя потолки на уставки",
        "ограничивает, а не назначает: пределы приходят из кейса через "
        "RuleContext, агент их не выводит и не смягчает",
        "молчит, когда давление или его пределы в контексте не объявлены, "
        "и тогда шаг совпадает с прогоном без агента бит в бит",
    )

    def restrictions(
        self, state: PolicyState, context: RuleContext
    ) -> tuple[PressureRestriction, ...]:
        corridor = pressure_corridor_of(context)
        if corridor is None:
            return ()
        found: list[PressureRestriction] = []
        for well in sorted(state.wells):
            observation = state.wells[well]
            if not observation.is_open:
                continue
            restriction = restriction_for(
                corridor,
                well,
                observation.role,
                observation.setpoint_m3_per_day,
            )
            if restriction is None:
                continue
            found.append(restriction)
        return tuple(found)

    def trace_for(
        self, state: PolicyState, restrictions: tuple[PressureRestriction, ...]
    ) -> tuple[LeveledTraceEntry, ...]:
        return tuple(
            LeveledTraceEntry(
                level=self.level,
                agent=self.name,
                entry=TraceEntry(
                    control_step=state.control_step,
                    well=restriction.well,
                    rule=Rule.R1,
                    inputs=restriction.as_inputs(),
                    decision=PRESSURE_CEILING_DECISION,
                ),
            )
            for restriction in restrictions
        )

    def propose(self, state: PolicyState, context: RuleContext) -> Proposal:
        restrictions = self.restrictions(state, context)
        return Proposal(
            level=self.level,
            agent=self.name,
            decisions=(),
            rule_by_decision=(),
            trace=self.trace_for(state, restrictions),
            bounds=tuple(item.as_bound() for item in restrictions),
        )
