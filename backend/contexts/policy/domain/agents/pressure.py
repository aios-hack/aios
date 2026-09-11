from __future__ import annotations

from dataclasses import dataclass

from backend.contexts.schedule.domain.schedule import EventKind, Role
from backend.contexts.policy.domain.policy import Rule, TraceEntry

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
                f"reservoir pressure {self.value_bar} bar is not positive: "
                f"the distance to the limit cannot be computed"
            )
        if not 0.0 < self.approach_fraction <= 1.0:
            raise ValueError(
                f"the corridor fraction for the approach threshold must lie in "
                f"(0, 1], got {self.approach_fraction}"
            )
        if self.floor_bar is None and self.ceiling_bar is None:
            raise ValueError(
                "a reservoir pressure corridor without a single limit: "
                "there is nothing to approach"
            )
        if (
            self.floor_bar is not None
            and self.ceiling_bar is not None
            and self.ceiling_bar <= self.floor_bar
        ):
            raise ValueError(
                f"the reservoir pressure ceiling {self.ceiling_bar} bar is not above "
                f"the floor {self.floor_bar} bar: the corridor is empty"
            )

    def width_bar(self) -> float:
        if self.floor_bar is not None and self.ceiling_bar is not None:
            return self.ceiling_bar - self.floor_bar
        known = self.floor_bar if self.ceiling_bar is None else self.ceiling_bar
        if known is None:
            raise ValueError(
                "the width of the reservoir pressure corridor is undefined: "
                "not a single limit is set"
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
                "the threshold for approaching the pressure limit is zero: "
                "by what factor to reduce the setpoint is undefined"
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
                f"{self.well}: the reservoir pressure ceiling is negative "
                f"({self.value_m3_per_day} m3/day): the bound is "
                f"not interpretable"
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
            f"{well}: the reservoir pressure limit is declared as approached, "
            f"but the limit value itself is not set: there is nothing to name "
            f"what the setpoint runs into"
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
        "reduces injection as the average reservoir pressure approaches the case "
        "ceiling, and production as it approaches the floor, by placing ceilings on setpoints",
        "constrains rather than assigns: the limits come from the case through "
        "RuleContext, and the agent neither derives nor relaxes them",
        "stays silent when the pressure or its limits are not declared in the context, "
        "and then the step matches a run without the agent bit for bit",
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
