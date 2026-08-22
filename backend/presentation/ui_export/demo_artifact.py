from __future__ import annotations

from datetime import date

from backend.core.contracts import (
    Constraints,
    FinalNpvArtifact,
    Groups,
    Lambda,
    LineItems,
    NpvTable,
    Role,
    Rule,
    RunArtifact,
    Schedule,
    ScheduleMeta,
    TraceEntry,
    WellOutage,
)

from backend.presentation.ui_export.demo_response import interval_rows, state_rows
from backend.presentation.ui_export.demo_rng import (
    DEMO_PROVENANCE,
    DEMO_SCALE,
    DEMO_SEED,
    GROUP_COUNT,
    Rng,
    control_events,
    demo_hash,
    initial_state,
    roles_of,
)

__all__ = ["DEMO_PROVENANCE", "DEMO_SEED", "build_demo_artifact", "demo_hash"]


_SHARES = {
    "deductions": 0.34,
    "opex_oil": 0.06,
    "opex_liquid": 0.05,
    "opex_injection": 0.03,
    "opex_wellstock": 0.08,
    "property_tax": 0.004,
    "event_costs": 0.002,
}


def _line_items(revenue: float, df: float) -> LineItems:
    parts = {name: share * revenue for name, share in _SHARES.items()}
    capex_esp = 0.011 * revenue
    ebitda = revenue - sum(parts.values())
    income_tax = 0.25 * max(0.0, ebitda)
    fcf = ebitda - income_tax - capex_esp
    return LineItems(
        revenue=revenue,
        capex_esp=capex_esp,
        ebitda=ebitda,
        income_tax=income_tax,
        fcf=fcf,
        df=df,
        discounted_fcf=fcf * df,
        **parts,
    )


def _npv_table(
    wells: tuple[str, ...], roles: dict[str, Role], t0: date, n_intervals: int, rng: Rng
) -> NpvTable:
    by_month: dict[int, LineItems] = {}
    for step in range(n_intervals):
        df = 1.0 / (1.1 ** (step / 12.0))
        revenue = DEMO_SCALE * (9.0e6 * (1.0 - 0.4 * step / max(1, n_intervals - 1)))
        by_month[step] = _line_items(revenue * rng.between(0.92, 1.08), df)
    by_year: dict[int, LineItems] = {}
    for step, items in by_month.items():
        year = t0.year + (t0.month - 1 + step) // 12
        merged = by_year.get(year)
        by_year[year] = (
            items if merged is None else _line_items(merged.revenue + items.revenue, merged.df)
        )
    share = {well: rng.between(-0.25, 1.0) if roles[well] is not Role.NONE else 0.0 for well in wells}
    by_well = {well: _line_items(DEMO_SCALE * 2.4e7 * share[well], 0.62) for well in wells}
    npv = sum(items.discounted_fcf for items in by_well.values())
    return NpvTable(by_year=by_year, by_month=by_month, by_well=by_well, npv_methodology=npv)


def _lambda(
    wells: tuple[str, ...], roles: dict[str, Role], t0: date, window_months: int, rng: Rng
) -> Lambda:
    injectors = tuple(well for well in wells if roles[well] is Role.INJ)
    producers = tuple(well for well in wells if roles[well] is Role.PROD)
    matrix: list[tuple[float, ...]] = []
    for row, _ in enumerate(producers):
        values: list[float] = []
        for col, _ in enumerate(injectors):
            near = abs(row - col * len(producers) / max(1, len(injectors)))
            strong = near < 3.0 or rng.unit() < 0.06
            values.append(round(rng.between(0.05, 0.9), 4) if strong else 0.0)
        matrix.append(tuple(values))
    end_months = t0.month - 1 + window_months
    return Lambda(
        window_start=t0,
        window_end=date(t0.year + end_months // 12, end_months % 12 + 1, t0.day),
        producers=producers,
        injectors=injectors,
        matrix=tuple(matrix),
        lag_months=3,
        amplitude=0.21,
        stability=0.74,
        rank=min(len(injectors), len(producers)),
        condition_number=12.8,
        achievability_ok={well: rng.unit() > 0.15 for well in injectors},
    )


def _groups(wells: tuple[str, ...], roles: dict[str, Role]) -> Groups:
    buckets: dict[str, list[str]] = {f"G{i + 1}": [] for i in range(GROUP_COUNT)}
    for index, well in enumerate(wells):
        buckets[f"G{index % GROUP_COUNT + 1}"].append(well)
    for members in buckets.values():
        if not any(roles[well] is Role.INJ for well in members):
            members.append(next(well for well in wells if roles[well] is Role.INJ))
    return Groups(
        groups={name: tuple(members) for name, members in buckets.items()},
        lambda_hash=demo_hash("lambda"),
        group_hash=demo_hash("groups"),
    )


def _trace(
    wells: tuple[str, ...], roles: dict[str, Role], n_intervals: int, rng: Rng
) -> tuple[TraceEntry, ...]:
    entries: list[TraceEntry] = []
    actors = [well for well in wells if roles[well] is not Role.NONE]
    for step in range(n_intervals):
        well = actors[step % len(actors)]
        if roles[well] is Role.INJ:
            rate = round(rng.between(120.0, 210.0), 1)
            entries.append(
                TraceEntry(
                    control_step=step,
                    well=well,
                    rule=Rule.R4,
                    inputs={
                        "injection_rate": rate,
                        "compensation": round(rng.between(0.8, 1.3), 3),
                    },
                    decision=f"SET_RATE {rate}",
                )
            )
            continue
        lrat = round(rng.between(35.0, 115.0), 1)
        entries.append(
            TraceEntry(
                control_step=step,
                well=well,
                rule=Rule.R1,
                inputs={
                    "watercut": round(rng.between(0.55, 0.97), 3),
                    "liquid_rate": lrat,
                },
                decision=f"SET_LRAT {lrat}",
            )
        )
    return tuple(entries)


def _constraints(
    wells: tuple[str, ...], roles: dict[str, Role], t0: date, n_intervals: int
) -> Constraints:
    span = range(t0.year, t0.year + (n_intervals + 11) // 12)
    outage_wells = [well for well in wells if roles[well] is Role.PROD][:3]
    return Constraints(
        injection_limits={year: 5_200_000.0 for year in span},
        liquid_limits={year: 9_100_000.0 for year in span},
        production_floors={year: 40.0 for year in span},
        watercut_limits={year: 0.96 for year in span},
        well_outages=tuple(
            WellOutage(
                well=well,
                control_step_from=min(12 * (index + 1), n_intervals - 2),
                control_step_to=min(12 * (index + 1) + 2, n_intervals - 1),
            )
            for index, well in enumerate(outage_wells)
        ),
        infrastructure={"kns_limit_m3_per_day": 14_500.0},
    )


def build_demo_artifact(
    wells: tuple[str, ...],
    n_control_dates: int,
    n_deck_dates: int,
    t0: date,
    seed: int = DEMO_SEED,
    tag: str = "base",
    submitted: bool = False,
) -> RunArtifact:
    rng = Rng(seed)
    n_intervals = n_control_dates - 1
    offset = n_deck_dates - n_control_dates
    roles = roles_of(wells)
    late = [well for well in wells if roles[well] is Role.NONE]
    commission_step = {
        well: min(18 + 9 * index, n_intervals - 1) for index, well in enumerate(late)
    }
    meta = ScheduleMeta(
        model="Model_Z",
        t0=t0,
        n_control_dates=n_control_dates,
        n_intervals=n_intervals,
        wells=wells,
        history_prefix_hash=demo_hash(f"history-{tag}"),
        fixed_events_hash=demo_hash(f"fixed-{tag}"),
        control_events_hash=demo_hash(f"control-{tag}"),
        provenance=DEMO_PROVENANCE,
    )
    schedule = Schedule(
        meta=meta,
        initial_state=initial_state(wells, roles, rng),
        fixed_deck_events=(),
        control_events=control_events(wells, roles, n_intervals, rng),
    )
    npv_table = _npv_table(wells, roles, t0, n_intervals, rng)
    final_npv = (
        FinalNpvArtifact(
            npv_table=npv_table,
            npv_methodology=npv_table.npv_methodology,
            source_run_id=demo_hash(f"run-{tag}"),
            source_response_hash=demo_hash(f"response-{tag}"),
            economics_config_hash=demo_hash(f"economics-{tag}"),
            methodology_version_hash=demo_hash(f"methodology-{tag}"),
        )
        if submitted
        else None
    )
    return RunArtifact(
        config_hash=demo_hash(f"config-{tag}"),
        schedule=schedule,
        state_at_date=state_rows(wells, roles, n_deck_dates, commission_step, offset, rng),
        interval_response=interval_rows(wells, roles, n_intervals, commission_step, rng),
        npv_table=npv_table,
        trace=_trace(wells, roles, n_intervals, rng),
        groups=_groups(wells, roles),
        lambda_=_lambda(wells, roles, t0, min(18, n_intervals), rng),
        constraints=_constraints(wells, roles, t0, n_intervals),
        converged=True,
        self_consistent=True,
        final_npv=final_npv,
    )
