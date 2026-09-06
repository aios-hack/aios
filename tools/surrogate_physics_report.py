"""Отчёт о физических инвариантах прогнозов суррогата — S-03/S-04.

Считает семь инвариантов `surrogate.physics_checks` на двух популяциях сразу
и кладёт их рядом в один отчёт:

* **прогноз** — то, что выдаёт production-суррогат на реальных расписаниях;
* **отклик** — то, что на тех же расписаниях выдал настоящий OPM.

Обе колонки нужны вместе. Отдельно взятый ноль флагов на прогнозе доказывает
только то, что параметризация модели не даёт нарушить инвариант, а не то, что
инвариант физически содержателен. Настоящий отклик OPM показывает, сколько
нарушений даёт сам измеренный ряд — и если модель «чище» симулятора, это
свойство её clamp'ов, а не её физичности. Куратору (31.08, 00:15:25) нужен
именно этот контраст, а не одно число.

Запуск:

    PYTHONPATH=. python tools/surrogate_physics_report.py \\
        --output data/surrogate/physics.json

Инструмент только читает: OPM не запускается, отсутствующий прогон — ошибка,
а не повод посчитать что-нибудь на месте (CLAUDE.md §3).
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import replace
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import conftest
from contracts import N_INTERVALS, Schedule, hash_schedule
from economics import load_response_artifact
from optimizer.runtime_artifacts import resolve_runtime_artifacts
from optimizer.schedule_search import load_environment
from optimizer.search_run import LAMBDA, NORMATIVES, RESPONSE
from surrogate.features import ScheduleFeatureizer
from surrogate.physics_checks import (
    BhpLimits,
    PhysicsReport,
    check_physics,
    lambda_column_sums,
)
from surrogate.raw_model_output import RawModelOutput, RawWellStepPrediction
from ui.artifact_io import _load_schedule

# Прогоны с настоящим откликом OPM, лежащие на manifold оптимизатора: это те
# расписания, которые контур действительно предлагал, а не широкие случайные
# возмущения обучающего датасета.
DEFAULT_RUNS = Path("data")
RUN_GLOB = "constrained-opm-*"

# Историческая часть StateAtDate — deck_date_index 0…146; прогнозная начинается
# со 147-й даты (`surrogate/adapter.py`).
_HISTORY_HORIZON = 147


class PhysicsReportError(RuntimeError):
    pass


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--runs-root",
        type=Path,
        default=DEFAULT_RUNS,
        help="каталог с прогонами OPM (schedule.json + response.json + result.json)",
    )
    parser.add_argument(
        "--glob", default=RUN_GLOB, help="маска подкаталогов внутри --runs-root"
    )
    parser.add_argument(
        "--reference",
        default="constrained-opm-feasible-final",
        help="прогон-опора для differential-инвариантов",
    )
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--oil-density", type=float, default=0.9131)
    return parser


def _load_run(directory: Path) -> tuple[Schedule, object, float]:
    for name in ("schedule.json", "response.json", "result.json"):
        if not (directory / name).is_file():
            raise PhysicsReportError(f"{directory}: нет {name}")
    schedule = _load_schedule(
        json.loads((directory / "schedule.json").read_text(encoding="utf-8"))
    )
    result = json.loads((directory / "result.json").read_text(encoding="utf-8"))
    if result["canonical_schedule_hash"] != hash_schedule(schedule):
        raise PhysicsReportError(f"{directory}: расписание не совпадает с result.json")
    response = load_response_artifact(directory / "response.json")
    return schedule, response, float(result["npv_opm"])


def _response_as_prediction(
    response, schedule: Schedule
) -> tuple[RawModelOutput, dict[str, int]]:
    """Настоящий отклик OPM в форме прогноза.

    ``RawWellStepPrediction`` отвергает отрицательные значения, а измеренный
    отклик их содержит: это перетоки, артефакт разбора UNSMRY. Они срезаются
    в ноль, и их число возвращается отдельно — молча терять такое нельзя, это
    и есть часть ответа на вопрос «нарушается ли где-то физика».
    """

    interval = {(r.control_step, r.well): r for r in response.interval_response}
    state = {(s.deck_date_index, s.well): s for s in response.state_at_date}
    wells = tuple(schedule.meta.wells)
    clamped: dict[str, int] = {}
    nodes: list[RawWellStepPrediction] = []
    for well in wells:
        for step in range(N_INTERVALS):
            measured = interval[(step, well)]
            at_date = state[(_HISTORY_HORIZON + step, well)]
            values = {
                "oil_mass_delta": measured.oil_mass_delta,
                "liquid_volume_delta": measured.liquid_volume_delta,
                "injection_volume_delta": measured.injection_volume_delta,
                "liquid_rate": at_date.liquid_rate,
                "injection_rate": at_date.injection_rate,
                "bhp": at_date.bhp,
            }
            for name, value in values.items():
                if value < 0.0:
                    clamped[name] = clamped.get(name, 0) + 1
            nodes.append(
                RawWellStepPrediction(
                    well=well,
                    control_step=step,
                    **{name: max(value, 0.0) for name, value in values.items()},
                )
            )
    return (
        RawModelOutput(
            canonical_schedule_hash=hash_schedule(schedule),
            wells=wells,
            nodes=tuple(nodes),
        ),
        clamped,
    )


def _summary(report: PhysicsReport) -> dict[str, object]:
    payload = report.as_dict()
    # Примеры полезны при разборе одного кандидата, но в сводном отчёте по
    # десятку прогонов они вытесняют числа. Счётчики полны и без них.
    payload.pop("examples", None)
    return payload


def main() -> int:
    args = _parser().parse_args()
    artifacts = resolve_runtime_artifacts()
    env = load_environment(
        model_dir=conftest.model_z_dir(),
        normatives_path=NORMATIVES,
        response_path=RESPONSE,
        checkpoint_path=artifacts.checkpoint,
        feature_context_path=artifacts.feature_context,
        npv_head_path=artifacts.npv_head,
        lambda_path=LAMBDA,
        oil_density_t_per_m3=args.oil_density,
    )
    featureizer = ScheduleFeatureizer()

    directories = sorted(
        path for path in args.runs_root.glob(args.glob) if path.is_dir()
    )
    if not directories:
        raise PhysicsReportError(f"{args.runs_root}/{args.glob}: прогонов не найдено")
    reference_dir = args.runs_root / args.reference
    if reference_dir not in directories:
        raise PhysicsReportError(f"опора {reference_dir} не входит в выборку")

    runs = {path.name: _load_run(path) for path in directories}
    reference_schedule, reference_response, _ = runs[args.reference]
    reference_measured, _ = _response_as_prediction(
        reference_response, reference_schedule
    )
    reference_predicted = env.model.predict(
        replace(
            featureizer.transform(reference_schedule, env.feature_context.context),
            lambda_edges=(),
        )
    ).output

    entries: list[dict[str, object]] = []
    for name, (schedule, response, npv) in runs.items():
        measured, clamped = _response_as_prediction(response, schedule)
        predicted = env.model.predict(
            replace(
                featureizer.transform(schedule, env.feature_context.context),
                lambda_edges=(),
            )
        ).output
        is_reference = name == args.reference
        entries.append(
            {
                "run": name,
                "npv_opm_rub": npv,
                "canonical_schedule_hash": hash_schedule(schedule),
                "response_hash": response.response_hash,
                "negatives_clamped_in_measured_response": clamped,
                "predicted": _summary(
                    check_physics(
                        predicted,
                        schedule=schedule,
                        reference=None if is_reference else reference_predicted,
                        reference_schedule=None if is_reference else reference_schedule,
                        lam=env.lambda_,
                        oil_density_t_per_m3=args.oil_density,
                    )
                ),
                "measured": _summary(
                    check_physics(
                        measured,
                        schedule=schedule,
                        reference=None if is_reference else reference_measured,
                        reference_schedule=None if is_reference else reference_schedule,
                        lam=env.lambda_,
                        oil_density_t_per_m3=args.oil_density,
                    )
                ),
            }
        )

    limits = BhpLimits.from_schedule(reference_schedule)
    column_sums = lambda_column_sums(env.lambda_)
    payload = {
        "format": "aios.surrogate-physics-report.v1",
        "provenance": {
            "checkpoint": str(artifacts.checkpoint),
            "feature_context": str(artifacts.feature_context),
            "npv_head": str(artifacts.npv_head),
            "source": artifacts.source,
            "lambda": str(LAMBDA),
            "reference_run": args.reference,
            "oil_density_t_per_m3": args.oil_density,
        },
        "bhp_limits_from_deck": {
            "producer_floor_bar": limits.producer_default,
            "injector_ceiling_bar": limits.injector_default,
            "wells_with_explicit_floor": len(limits.producer_floor),
            "wells_with_explicit_ceiling": len(limits.injector_ceiling),
        },
        "lambda_column_sums": {
            # CRM-условие Σ_p f[p][i] ≤ 1 к размерной λ неприменимо; число
            # столбцов сверх единицы публикуется как факт об артефакте, а не
            # как нарушение физики прогноза.
            "n_injectors": len(column_sums),
            "n_above_one": sum(1 for value in column_sums.values() if value > 1.0),
            "max": max(column_sums.values()) if column_sums else None,
            "min": min(column_sums.values()) if column_sums else None,
        },
        "runs": entries,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(payload, ensure_ascii=False, indent=1, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    print(f"прогонов: {len(entries)}, опора: {args.reference}")
    print(f"{'прогон':34} {'прогноз: блок/пред':>20} {'отклик: блок/пред':>20}")
    for entry in entries:
        predicted = entry["predicted"]
        measured = entry["measured"]
        print(
            f"{entry['run']:34} "
            f"{predicted['blocking_count']:>9}/{predicted['warning_count']:<10} "
            f"{measured['blocking_count']:>9}/{measured['warning_count']:<10}"
        )
    print(f"\nотчёт: {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
