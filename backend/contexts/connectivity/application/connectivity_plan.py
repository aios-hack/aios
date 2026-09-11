from __future__ import annotations

from backend.contexts.connectivity.application.campaign import CampaignSetup, level_factor
from backend.contexts.connectivity.domain.doe import DoEPlan
from backend.contexts.simulation.domain.perturbation_design import (
    LevelPerturbation,
    PerturbationFamily,
    PerturbationPlan,
    PerturbationSpec,
    PlanConfig,
)


def specs_of(plan: DoEPlan, batch: int, first_step: int = 0) -> tuple[PerturbationSpec, ...]:
    return tuple(
        PerturbationSpec(
            scenario_id=f"lambda-b{batch}-{row.run_index:04d}",
            family=PerturbationFamily.LEVELS,
            seed=plan.seed + row.run_index,
            levels=tuple(
                LevelPerturbation(well=well, from_step=first_step, factor=level_factor(level, plan.amplitude))
                for well, level in sorted(row.levels.items())
            ),
        )
        for row in plan.rows
    )


def campaign_plan(setup_result: CampaignSetup, seed: int) -> PerturbationPlan:
    specs = tuple(
        spec
        for batch, plan in enumerate(setup_result.plans)
        for spec in specs_of(plan, batch)
    )
    return PerturbationPlan(config=PlanConfig(), seed=seed, specs=specs)
