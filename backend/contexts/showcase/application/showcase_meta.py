from __future__ import annotations

from pathlib import Path
from typing import Any

from backend.contexts.constraints.domain.config import (
    ChargeInitialEsp,
    DEFAULT_NORMATIVES_2007,
    NormativeSet,
    Policies,
    QuantizationPolicy,
)
from backend.contexts.economics.domain.esp import ESP_CATALOG_2007
from backend.contexts.policy.domain.agents.registry import DEFAULT_REGISTRY
from backend.contexts.reservoir.application.deck import (
    load_oil_density_by_well,
    load_wellheads,
)
from backend.contexts.reservoir.application.well_geometry import DEFAULT_DECK_PATH
from backend.contexts.runs.domain.run_artifact import RunArtifact
from backend.contexts.showcase.application.notices import notice_fields
from backend.contexts.showcase.application.scenarios import (
    ScenarioRobustness,
    WorstRegret,
)
from backend.contexts.showcase.infrastructure.synthetic_artifact import (
    DEMO_PROVENANCE,
    DEMO_SEED,
)
from backend.shared.errors import DomainError
from backend.shared.paths import project_root

BASE_ID = "base"
WHATIF_ID = "whatif-injection-cut"
DEFAULT_OUT_DIR: Path = project_root() / "frontend" / "public" / "data"
_DEFAULT_DENSITY = 860.0


def _oil_densities(wells: Any) -> dict[str, float]:
    from backend.shared.resources import model_z_dir

    names = tuple(wells)
    try:
        measured = load_oil_density_by_well(names, model_z_dir())
    except (DomainError, FileNotFoundError, ValueError, OSError):
        return {well: _DEFAULT_DENSITY for well in names}
    return {well: measured.get(well, _DEFAULT_DENSITY) for well in names}


DEMO_ROBUSTNESS: dict[str, ScenarioRobustness] = {
    BASE_ID: ScenarioRobustness(
        ood_score=0.18,
        ood_threshold=0.5,
        worst_regret=WorstRegret(
            scenario_id="holdout-outage-and-injection-cap",
            value_rub=201_000_000.0,
            part="holdout",
        ),
    ),
    WHATIF_ID: ScenarioRobustness(),
}


def confirmed_base_robustness(
    npv_rub: float, source_run_id: str
) -> ScenarioRobustness:
    measured = DEMO_ROBUSTNESS[BASE_ID]
    return ScenarioRobustness(
        ood_score=measured.ood_score,
        ood_threshold=measured.ood_threshold,
        worst_regret=measured.worst_regret,
        final_npv_rub=npv_rub,
        final_npv_run_id=source_run_id,
        run_validation_clean=True,
    )


_BASE_NORMATIVES = NormativeSet(**DEFAULT_NORMATIVES_2007, esp_catalog=ESP_CATALOG_2007)


_BASE_POLICIES = Policies(
    charge_initial_esp=ChargeInitialEsp.NOT_CHARGED,
    quantization_policy=QuantizationPolicy.NONE,
)


def demo_meta(kind: str) -> dict[str, Any]:
    return {
        "provenance": DEMO_PROVENANCE,
        "synthetic": True,
        "seed": DEMO_SEED,
        "kind": kind,
        **notice_fields("showcase.notice.demo"),
    }


HIERARCHY_PROVENANCE = "policy-hierarchy-trace"


def hierarchy_meta(artifact: RunArtifact) -> dict[str, Any]:
    return {
        "provenance": HIERARCHY_PROVENANCE,
        "synthetic": False,
        "kind": "hierarchy",
        "lambda_measured": any(
            weight != 0.0 for row in artifact.lambda_.matrix for weight in row
        ),
        "agent_registry": list(DEFAULT_REGISTRY.names()),
        **notice_fields("showcase.notice.hierarchy"),
    }


def deck_scale(deck_path: str | Path = DEFAULT_DECK_PATH) -> tuple[str, ...]:
    heads = load_wellheads(deck_path)
    return tuple(sorted(heads, key=lambda name: (len(name), name)))
