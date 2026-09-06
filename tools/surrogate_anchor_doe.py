"""Пакет OPM-прогонов вокруг якоря — новая информация для суррогата.

Замеры показали, что инженерия признаков исчерпана: пять моделей от одной
координаты до GBDT ложатся в Spearman 0.83 ± 0.02 и статистически неотличимы
(`tools/surrogate_baseline_comparison.py`), а признак достижимости, выводимый
из расписания, не даёт ничего (`tools/surrogate_information_ceiling.py`).
Двигает только новая информация, то есть настоящие прогоны симулятора на том
manifold, где контур предлагает кандидатов.

Пакет строит возмущения семейств §7.1 плана вокруг якорного расписания:
общие уровни отбора и закачки. Семейства разведены намеренно — differential-
инварианты физики (`surrogate.physics_checks`) идентифицируемы только на паре,
где менялась одна закачка, и комбинированный вариант считается отдельно.

Каждый кандидат проходит полный submission-тракт: канонизация, статический
валидатор, эмиссия дека, OPM Flow, разбор отклика, эталонная экономика. Число
ЧДД берётся из прогона, а не из суррогата.

Замеренное время одного прогона Model_Z на этой машине — **824.87 с**
(385 шагов, 1041 итерация Ньютона), поэтому пакет из десяти кандидатов идёт
около двух с половиной часов последовательно.

Запуск:

    PYTHONPATH=. python tools/surrogate_anchor_doe.py --dry-run   # без OPM
    PYTHONPATH=. python tools/surrogate_anchor_doe.py --only levels-prod-p050
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from dataclasses import replace
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import tempfile

import conftest
from bridge import submit_schedule
from bridge.opm_deck import OpmDeckEmitter
from bridge.runner import deck_hashes, summary_spec_hash
from config.schema import default_config
from contracts import ArtifactHashes, ControlEvent, EventKind, Schedule, hash_schedule
from economics import load_normatives
from optimizer.runtime_artifacts import resolve_runtime_artifacts
from optimizer.schedule_search import load_environment
from optimizer.search_run import (
    CONSTRAINTS_PATH,
    LAMBDA,
    MODEL_DIR,
    NORMATIVES,
    RESPONSE,
    SEED,
)
from schedule import canonicalize, validate_static
from schedule.build import load_schedule
from schedule.canonical import canonical_part_hash
from ui.scenarios import load_constraints_file

FORMAT = "aios.surrogate-anchor-doe.v1"
DEFAULT_OUT = Path("data/anchor-doe")

# Потолок `SET_LRAT` — контрактный (`ControlEvent`), 500 м³/сут. Уставки якоря
# лежат в 0…110 и 10…245, поэтому ±5% в него не упирается; ограничение всё
# равно применяется, чтобы масштаб нельзя было задать любым.
MAX_SCALE = 1.5
MIN_SCALE = 0.5

# Семейства §7.1: уровни отбора и уровни закачки порознь, плюс одна
# комбинация — та, что `DISCUSSIONS.md` нашла лучшей на repaired anchor
# (+5% отбор / +2.5% закачка дали +97 млн ₽).
PLAN: tuple[tuple[str, float, float], ...] = (
    # Якорь как контроль: без него неизвестно, новые ли нарушения динамики у
    # кандидата или они уже есть в базовом расписании. `DISCUSSIONS.md`
    # отмечает, что коридор компенсации задан неверно и эталон формально
    # «в нарушении» на всех 224 шагах, — проверяем это своими глазами.
    ("anchor", 1.000, 1.000),
    ("levels-prod-m050", 0.950, 1.000),
    ("levels-prod-m025", 0.975, 1.000),
    ("levels-prod-p025", 1.025, 1.000),
    ("levels-prod-p050", 1.050, 1.000),
    ("levels-inj-m050", 1.000, 0.950),
    ("levels-inj-m0125", 1.000, 0.9875),
    ("levels-inj-p0125", 1.000, 1.0125),
    ("levels-inj-p025", 1.000, 1.025),
    ("levels-inj-p050", 1.000, 1.050),
    ("levels-prod-p050-inj-p025", 1.050, 1.025),
)


class DoeError(RuntimeError):
    pass


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument(
        "--only",
        action="append",
        help="прогнать только названные кандидаты (можно повторять)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="собрать и проверить расписания, не запуская OPM",
    )
    return parser


def perturb(schedule: Schedule, *, producers: float, injectors: float) -> Schedule:
    """Масштабирование уставок отбора и закачки как единого уровня.

    Меняются только `SET_LRAT` и `SET_RATE`. Открытия, остановки и переводы
    остаются как есть: это отдельные семейства кандидатов, и смешивать их с
    уровнями значит потерять идентифицируемость differential-инвариантов.
    """

    for name, value in (("producers", producers), ("injectors", injectors)):
        if not MIN_SCALE <= value <= MAX_SCALE:
            raise DoeError(f"масштаб {name}={value} вне [{MIN_SCALE}, {MAX_SCALE}]")

    events: list[ControlEvent] = []
    for event in schedule.control_events:
        if event.kind is EventKind.SET_LRAT and event.value is not None:
            events.append(replace(event, value=event.value * producers))
        elif event.kind is EventKind.SET_RATE and event.value is not None:
            events.append(replace(event, value=event.value * injectors))
        else:
            events.append(event)
    return canonicalize(replace(schedule, control_events=tuple(events)))


def main() -> int:
    args = _parser().parse_args()
    anchor = canonicalize(load_schedule(conftest.model_z_dir() / "Model_Z_sch.inc"))
    anchor_hash = hash_schedule(anchor)
    print(f"якорь: {anchor_hash[:16]}…, управляющих событий {len(anchor.control_events)}")

    selected = [row for row in PLAN if not args.only or row[0] in set(args.only)]
    if not selected:
        raise DoeError(f"ни один кандидат не совпал с --only {args.only}")

    candidates: list[tuple[str, Schedule, float, float]] = []
    for name, producers, injectors in selected:
        candidate = perturb(anchor, producers=producers, injectors=injectors)
        report = validate_static(candidate)
        if not report.ok:
            kinds = ", ".join(
                f"{kind.value}×{len(items)}" for kind, items in report.by_kind().items()
            )
            raise DoeError(f"{name}: статический валидатор не пройден: {kinds}")
        if name != "anchor" and hash_schedule(candidate) == anchor_hash:
            raise DoeError(f"{name}: расписание совпало с якорем — возмущение пустое")
        candidates.append((name, candidate, producers, injectors))
        print(
            f"  {name:28} отбор ×{producers:.4f} закачка ×{injectors:.4f} "
            f"→ {hash_schedule(candidate)[:12]}…  статически чист"
        )

    if args.dry_run:
        print(f"\nсухой прогон: {len(candidates)} кандидатов собраны и валидны, OPM не запускался")
        return 0

    constraints = load_constraints_file(CONSTRAINTS_PATH)
    normatives = load_normatives(NORMATIVES)
    artifacts = resolve_runtime_artifacts()
    env = load_environment(
        model_dir=MODEL_DIR,
        normatives_path=NORMATIVES,
        response_path=RESPONSE,
        checkpoint_path=artifacts.checkpoint,
        feature_context_path=artifacts.feature_context,
        npv_head_path=artifacts.npv_head,
        lambda_path=LAMBDA,
    )
    emitter = OpmDeckEmitter(MODEL_DIR)
    args.out.mkdir(parents=True, exist_ok=True)
    rows: list[dict[str, object]] = []

    for index, (name, candidate, producers, injectors) in enumerate(candidates, 1):
        directory = args.out / name
        directory.mkdir(parents=True, exist_ok=True)
        # Хеши артефактов принадлежат конкретному деку, поэтому конфиг
        # собирается на каждого кандидата, а не один раз на пакет.
        with tempfile.TemporaryDirectory() as scratch:
            deck = emitter.emit(candidate, Path(scratch) / "deck")
            hashes = deck_hashes(deck, candidate)
            summary_hash = summary_spec_hash(deck.summary_plan.spec)
        config = default_config(
            normatives,
            ArtifactHashes(
                deck_hash=hashes.deck_hash,
                history_prefix_hash=canonical_part_hash(candidate.initial_state),
                summary_spec_hash=summary_hash,
                groups_hash=env.groups.group_hash,
                dataset_version_hash=env.model.dataset_hash,
                surrogate_checkpoint_hash=env.model.version,
            ),
            global_seed=SEED,
        )
        started = time.monotonic()
        print(f"\n[{index}/{len(candidates)}] {name}: запуск OPM…", flush=True)
        result = submit_schedule(
            candidate,
            MODEL_DIR,
            directory / "work",
            config,
            constraints=constraints,
            strict=False,
        )
        elapsed = time.monotonic() - started
        # `final_npv` пуст ровно тогда, когда цепочка до него не дошла:
        # несошедшийся прогон отклика не даёт, а без отклика нет ни динамики,
        # ни денег. Подставлять заглушку запрещено правилом 6 репозитория.
        npv = None if result.final_npv is None else result.final_npv.npv_methodology
        dynamic = result.dynamic_report
        row = {
            "name": name,
            "producer_scale": producers,
            "injector_scale": injectors,
            "canonical_schedule_hash": hash_schedule(candidate),
            "npv_rub": npv,
            "sound": result.sound,
            "opm_run_id": result.opm_run.run_id,
            "response_hash": None if result.response is None else result.response.response_hash,
            "n_dynamic_violations": (
                None if dynamic is None else len(dynamic.violations)
            ),
            "violations_by_kind": (
                {}
                if dynamic is None
                else {
                    kind: sum(1 for v in dynamic.violations if v.kind is kind_enum)
                    for kind_enum, kind in sorted(
                        {(v.kind, v.kind.value) for v in dynamic.violations},
                        key=lambda item: item[1],
                    )
                }
            ),
            "failed_identities": [
                {"name": check.name, "detail": check.detail}
                for check in result.failed_identities
            ],
            "wallclock_seconds": elapsed,
        }
        rows.append(row)
        (directory / "result.json").write_text(
            json.dumps(row, ensure_ascii=False, indent=1, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        shown = "нет отклика" if npv is None else f"{npv/1e9:.4f} млрд ₽"
        print(
            f"  ЧДД {shown}, sound={result.sound}, "
            f"нарушений динамики {row['n_dynamic_violations']}, {elapsed/60:.1f} мин",
            flush=True,
        )

    payload = {
        "format": FORMAT,
        "anchor_canonical_schedule_hash": anchor_hash,
        "normatives": str(NORMATIVES),
        "constraints": str(CONSTRAINTS_PATH),
        "runs": rows,
    }
    (args.out / "doe.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=1, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(f"\nотчёт: {args.out / 'doe.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
