"""Выгрузка найденного плана G5 в витрину отдельным сценарием.

θ* берётся из `cmaes.json` — поиск заново не гоняется, расписание
восстанавливается за секунды. Отклик здесь **предсказан суррогатом**, не
измерен: в метаданных это сказано явным полем `prediction`, потому что на
экране «наш план» рядом с базовым прогоном OPM выглядит равноправным, а
равноправным не является. Когда G7 отдаст настоящий отклик, сценарий
перевыгружается на нём, и пометка снимается.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from aios_backend.core.contracts import Constraints, RunArtifact, Theta
from aios_backend.core.contracts.hashing import canonical_bytes, hash_schedule
from aios_backend.domain.economics import analyze_base_case, load_response_artifact
from aios_backend.domain.connectivity.groups import GroupingParams, build_groups
from aios_backend.domain.connectivity.measure import load_lambda
from aios_backend.application.optimization.schedule_search import load_environment, make_evaluator, make_policy
from aios_backend.infrastructure.resources import chdd_python_dir, model_z_dir
from aios_backend.domain.policy.fixed_point import resolve
from aios_backend.domain.policy.theta import default_theta
from aios_backend.domain.schedule import parse_schedule
from aios_backend.presentation.ui_export.artifact_io import dump_bundle
from aios_backend.presentation.ui_export.demo import export_scenario
from aios_backend.presentation.ui_export.scenarios import export_scenarios_json

import hashlib

DATASET = Path("../dataset-700/model-task34-700")
LAMBDA = Path("data/lambda-window-2007/lambda.json")
CMAES = Path("data/lambda-window-2007/cmaes.json")
RESPONSE = Path("data/base_case/response.json")
OUT = Path("frontend/public/data")
SCENARIO_ID = "policy-plan"
FINAL_CAP = 4


def main() -> int:
    saved = json.loads(CMAES.read_text(encoding="utf-8"))
    base_theta = default_theta()
    theta = Theta(values=dict(saved["theta"]), bounds=base_theta.bounds)

    model_dir = model_z_dir()
    env = load_environment(
        model_dir=model_dir,
        normatives_path=chdd_python_dir() / "input" / "Нормативы_ЧДД.xlsx",
        response_path=RESPONSE,
        checkpoint_path=DATASET / "model.pt",
        feature_context_path=DATASET / "feature_context.json",
        lambda_path=LAMBDA,
    )
    trace_sink: dict = {}
    initial = load_response_artifact(RESPONSE)
    result = resolve(
        make_policy(env, theta, trace_sink), make_evaluator(env), initial, FINAL_CAP
    )
    best = max(result.visited, key=lambda item: item.npv)
    schedule = best.schedule
    actual = hash_schedule(schedule)
    print(f"восстановлен план: {actual}", flush=True)
    if actual != saved["canonical_schedule_hash"]:
        print(f"ХЕШ РАЗОШЁЛСЯ с записанным {saved['canonical_schedule_hash']}", flush=True)
        return 3

    predicted = make_evaluator(env)(schedule).state
    parsed = parse_schedule((model_dir / "Model_Z_sch.inc").read_bytes())
    analysis = analyze_base_case(
        predicted, parsed.dates, parsed.t0_deck_date_index, env.normatives, env.policies
    )
    influence = load_lambda(LAMBDA)
    groups, _ = build_groups(
        influence, GroupingParams(), extra_wells=schedule.meta.wells
    )
    artifact = RunArtifact(
        config_hash=hashlib.sha256(
            canonical_bytes({"normatives": env.normatives, "policies": env.policies})
        ).hexdigest(),
        schedule=schedule,
        state_at_date=predicted.state_at_date,
        interval_response=predicted.interval_response,
        npv_table=analysis.table,
        trace=trace_sink["trace"].entries if "trace" in trace_sink else (),
        groups=groups,
        lambda_=influence,
        constraints=Constraints(),
        converged=result.converged,
        self_consistent=False,
        final_npv=None,
    )
    meta = {
        "provenance": "policy-search-candidate",
        "synthetic": False,
        "prediction": True,
        "lambda_measured": True,
        "source_run_id": f"surrogate-search:{env.model.version[:12]}",
        "response_hash": predicted.response_hash,
        "notice_ru": (
            "Наш план: θ* найдена CMA-ES, отклик предсказан суррогатом, "
            "настоящим прогоном OPM ещё не подтверждён"
        ),
        "notice_en": (
            "Our plan: θ* found by CMA-ES, response predicted by the surrogate, "
            "not yet confirmed by a real OPM run"
        ),
    }
    written = export_scenario(
        artifact,
        OUT / SCENARIO_ID,
        {kind: dict(meta, kind=kind) for kind in ("timeline", "graph", "npv", "trace")},
    )
    bundle = OUT / "bundles" / f"{SCENARIO_ID}.json"
    dump_bundle(artifact, bundle)
    written.append(bundle)
    index = export_scenarios_json(
        [
            OUT / "bundles" / "base.json",
            OUT / "bundles" / "whatif-injection-cut.json",
            bundle,
        ],
        OUT / "scenarios.json",
    )
    written.append(index)
    for path in written:
        print(path, flush=True)
    print(
        f"\nЧДД плана по суррогату: {analysis.npv_methodology / 1e9:.3f} млрд, "
        f"событий {len(schedule.control_events)}, сошлось: {result.converged}",
        flush=True,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
