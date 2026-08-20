"""Реальный `RunArtifact` базового прогона Model_Z. Задача G3.

Заменяет `"provenance": "synthetic-demo"` на данные настоящего расчёта:
`schedule`, `state_at_date`, `interval_response` и `npv_table` берутся из
отклика настоящего прогона OPM (`aios/data/base_case/response.json`,
собирается задачей G1 — `bridge.run_base_case` → `save_response_artifact`)
и настоящей экономики (`economics.analyze_base_case`).

`groups`/`lambda_` — не настоящая оценка связности. Измерить λ честно
можно только серией прогонов с отклонениями закачки (`connectivity`,
ортогональный план экспериментов) — такой серии нет, один базовый прогон
её не даёт. Здесь — тривиальная, но не фиктивная заглушка: одна группа на
весь фонд, нулевая матрица влияния той же формы, что у настоящей `Lambda`
(producers × injectors), хеши посчитаны настоящими
`connectivity.groups.lambda_hash`/`group_hash`, а не RNG. Не выдаётся за
измерение — `matrix` заполнена нулями, а не подобранными числами.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from contracts import (
    Constraints,
    Groups,
    Lambda,
    NormativeSet,
    Policies,
    Role,
    RunArtifact,
    canonical_bytes,
)
from connectivity.groups import GroupingParams, group_hash, lambda_hash
from economics import analyze_base_case, load_response_artifact
from schedule import build_schedule, parse_schedule

REAL_PROVENANCE = "model-z-base-run"
REAL_NOTICE_RU = "Настоящий расчёт: базовый прогон OPM без перекладки, эталонная методика ЧДД"
REAL_NOTICE_EN = "Real result: OPM baseline run with zero retiming, reference NPV methodology"

_SCHEDULE_INCLUDE = "Model_Z_sch.inc"

DEFAULT_RESPONSE_PATH: Path = (
    Path(__file__).resolve().parents[1] / "data" / "base_case" / "response.json"
)


@dataclass(frozen=True, slots=True)
class BaseArtifactResult:
    artifact: RunArtifact
    source_run_id: str
    response_hash: str


def real_meta(kind: str, result: BaseArtifactResult) -> dict[str, Any]:
    return {
        "provenance": REAL_PROVENANCE,
        "synthetic": False,
        "kind": kind,
        "source_run_id": result.source_run_id,
        "response_hash": result.response_hash,
        "notice_ru": REAL_NOTICE_RU,
        "notice_en": REAL_NOTICE_EN,
    }


def _economics_config_hash(normatives: NormativeSet, policies: Policies) -> str:
    payload = {"normatives": normatives, "policies": policies}
    return hashlib.sha256(canonical_bytes(payload)).hexdigest()


def _trivial_connectivity(schedule) -> tuple[Lambda, Groups]:
    """Групповая заглушка честной формы — см. докстринг модуля."""

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
) -> BaseArtifactResult:
    """Настоящий `RunArtifact` базового прогона. `NotImplementedError`-стиль:

    падает с понятной ошибкой, если `response_path` не существует, вместо
    того чтобы тихо подменить синтетикой (`economics.load_response_artifact`
    уже так и делает).
    """

    artifact = load_response_artifact(response_path)
    raw = (Path(model_dir) / _SCHEDULE_INCLUDE).read_bytes()
    parsed = parse_schedule(raw)
    schedule = build_schedule(parsed, raw, provenance=REAL_PROVENANCE)
    analysis = analyze_base_case(
        artifact, parsed.dates, parsed.t0_deck_date_index, normatives, policies
    )
    lambda_, groups = _trivial_connectivity(schedule)

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
        # Нет цикла политика-суррогат для базового прогона (нулевая
        # перекладка) — нечему не сойтись. См. докстринг модуля.
        converged=True,
        self_consistent=True,
        final_npv=None,
    )
    return BaseArtifactResult(
        artifact=run_artifact,
        source_run_id=artifact.source_run_id,
        response_hash=artifact.response_hash,
    )
