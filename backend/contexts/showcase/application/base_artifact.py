
from __future__ import annotations

from backend.contexts.showcase.application.notices import apply_notice, notice_fields

import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from backend.contexts.constraints.domain.constraints import Constraints
from backend.contexts.connectivity.domain.connectivity import Groups, Lambda
from backend.contexts.constraints.domain.config import NormativeSet, Policies
from backend.contexts.schedule.domain.schedule import Role
from backend.contexts.runs.domain.run_artifact import RunArtifact
from backend.shared.hashing import canonical_bytes
from backend.shared.paths import data_root
from backend.contexts.connectivity.domain.groups import GroupingParams, group_hash, lambda_hash
from backend.contexts.economics.application.base_case import (
    analyze_base_case,
    load_response_artifact,
)
from backend.contexts.schedule.domain.build import build_schedule
from backend.contexts.schedule.domain.lossless import parse_schedule

REAL_PROVENANCE = "model-z-base-run"

_SCHEDULE_INCLUDE = "Model_Z_sch.inc"

DEFAULT_RESPONSE_PATH: Path = data_root() / "base_case" / "response.json"


@dataclass(frozen=True, slots=True)
class BaseArtifactResult:
    artifact: RunArtifact
    source_run_id: str
    response_hash: str
    lambda_measured: bool = False


def real_meta(kind: str, result: BaseArtifactResult) -> dict[str, Any]:
    meta: dict[str, Any] = {
        "provenance": REAL_PROVENANCE,
        "synthetic": False,
        "kind": kind,
        "source_run_id": result.source_run_id,
        "response_hash": result.response_hash,
        **notice_fields("showcase.notice.real"),
    }
    if kind == "graph":
        meta["lambda_measured"] = result.lambda_measured
        apply_notice(
            meta,
            "showcase.notice.graph_lambda_measured"
            if result.lambda_measured
            else "showcase.notice.graph_lambda_absent",
        )
    return meta


def _economics_config_hash(normatives: NormativeSet, policies: Policies) -> str:
    payload = {"normatives": normatives, "policies": policies}
    return hashlib.sha256(canonical_bytes(payload)).hexdigest()


def _trivial_connectivity(schedule) -> tuple[Lambda, Groups]:
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


def build_base_artifact(
    normatives: NormativeSet,
    policies: Policies,
    *,
    response_path: Path | str = DEFAULT_RESPONSE_PATH,
    model_dir: Path,
    lambda_path: Path | str | None = None,
) -> BaseArtifactResult:
    artifact = load_response_artifact(response_path)
    raw = (Path(model_dir) / _SCHEDULE_INCLUDE).read_bytes()
    parsed = parse_schedule(raw)
    schedule = build_schedule(parsed, raw, provenance=REAL_PROVENANCE)
    analysis = analyze_base_case(
        artifact, parsed.dates, parsed.t0_deck_date_index, normatives, policies
    )
    if lambda_path is None:
        lambda_, groups = _trivial_connectivity(schedule)
        lambda_measured = False
    else:
        from backend.contexts.connectivity.domain.groups import build_groups
        from backend.contexts.connectivity.domain.measure import load_lambda

        lambda_ = load_lambda(lambda_path)
        groups, _ = build_groups(
            lambda_, GroupingParams(), extra_wells=schedule.meta.wells
        )
        lambda_measured = True

    run_artifact = RunArtifact(
        config_hash=_economics_config_hash(normatives, policies),
        schedule=schedule,
        state_at_date=artifact.state_at_date,
        interval_response=artifact.interval_response,
        npv_table=analysis.table,
        trace=(),
        groups=groups,
        lambda_=lambda_,
        constraints=Constraints(),
        converged=True,
        self_consistent=True,
        final_npv=None,
    )
    return BaseArtifactResult(
        artifact=run_artifact,
        source_run_id=artifact.source_run_id,
        response_hash=artifact.response_hash,
        lambda_measured=lambda_measured,
    )
