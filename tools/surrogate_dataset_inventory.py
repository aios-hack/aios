"""Инвентаризация обучающего датасета суррогата — S-05.

Отвечает на один вопрос: сколько независимых расписаний с настоящим откликом
OPM лежит на диске и хватает ли их, чтобы воспроизвести метрики карточки
(S-02). Единица счёта — **расписание**, а не строка манифеста и не узел
`скважина × месяц`: один и тот же `canonical_schedule_hash` встречается в
манифесте по многу раз (повторы, попадания в кеш), и складывать их значит
объявить 11 миллионов узлов одиннадцатью миллионами независимых примеров —
ровно та ошибка, из-за которой holdout ничего не доказывал.

Прогон считается пригодным, когда у него есть и запись в манифесте со
статусом `OK`, и файлы отклика на диске. Отсутствие файлов — не повод
промолчать: они перечисляются поимённо, потому что это и есть содержание
задачи H-04 «получить датасет».

Запуск:

    PYTHONPATH=. python tools/surrogate_dataset_inventory.py \\
        --root ../dataset-700/dataset-main \\
        --root ../dataset-700/dataset-extra-500 \\
        --output out/dataset-inventory.json
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

FORMAT = "aios.surrogate-dataset-inventory.v1"

# Что OPM оставляет после прогона и что читает `bridge.response_loader`.
# Отклика в виде `response.json` на диске нет и не должно быть: он собирается
# из бинарных выгрузок, а не хранится (CLAUDE.md §5 — производное не хранится).
RUN_ARTIFACTS: tuple[str, ...] = ("MODEL_Z.SMSPEC", "MODEL_Z.UNSMRY")


class InventoryError(RuntimeError):
    pass


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--root",
        type=Path,
        action="append",
        required=True,
        help="каталог с manifest.jsonl и runs/ (можно повторять)",
    )
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--max-missing-listed",
        type=int,
        default=25,
        help="сколько недостающих прогонов перечислить поимённо",
    )
    return parser


def _rows(root: Path) -> list[dict]:
    manifest = root / "manifest.jsonl"
    if not manifest.is_file():
        raise InventoryError(f"{root}: нет manifest.jsonl")
    rows = []
    for number, line in enumerate(manifest.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError as error:
            raise InventoryError(f"{manifest}:{number}: {error}") from error
    return rows


def main() -> int:
    args = _parser().parse_args()
    roots = [root for root in args.root]
    for root in roots:
        if not root.is_dir():
            raise InventoryError(f"{root}: каталога нет")

    # Расписание → лучшая известная запись. «Лучшая» — та, что со статусом OK
    # и с артефактами на диске: одно и то же расписание могло падать в одном
    # прогоне и посчитаться в другом.
    best: dict[str, dict] = {}
    per_root: dict[str, Counter] = defaultdict(Counter)
    statuses: Counter = Counter()
    synthetic = 0

    for root in roots:
        for row in _rows(root):
            statuses[row.get("status", "?")] += 1
            if row.get("synthetic"):
                synthetic += 1
                continue
            schedule_hash = row.get("canonical_schedule_hash")
            if not schedule_hash:
                continue
            run_dir = root / "runs" / str(row.get("run_id", ""))
            present = [
                name for name in RUN_ARTIFACTS if (run_dir / "output" / name).is_file()
            ]
            record = {
                "root": str(root),
                "run_id": row.get("run_id"),
                "scenario_id": row.get("scenario_id"),
                "family": row.get("family"),
                "status": row.get("status"),
                "response_hash": row.get("response_hash", ""),
                "run_dir": str(run_dir),
                "artifacts_present": present,
                "complete": row.get("status") == "OK" and len(present) == len(RUN_ARTIFACTS),
            }
            per_root[str(root)][row.get("family", "?")] += 1
            current = best.get(schedule_hash)
            if current is None or (record["complete"] and not current["complete"]):
                best[schedule_hash] = record

    families = Counter(record["family"] for record in best.values())
    complete = {h: r for h, r in best.items() if r["complete"]}
    families_complete = Counter(record["family"] for record in complete.values())
    missing = sorted(
        (
            {
                "canonical_schedule_hash": schedule_hash,
                "scenario_id": record["scenario_id"],
                "family": record["family"],
                "status": record["status"],
                "expected_files": [
                    f"{record['run_dir']}/output/{name}"
                    for name in RUN_ARTIFACTS
                    if name not in record["artifacts_present"]
                ],
            }
            for schedule_hash, record in best.items()
            if not record["complete"]
        ),
        key=lambda item: (item["family"] or "", item["scenario_id"] or ""),
    )

    payload = {
        "format": FORMAT,
        "roots": [str(root) for root in roots],
        "manifest_rows": sum(statuses.values()),
        "manifest_statuses": dict(sorted(statuses.items())),
        "synthetic_rows_excluded": synthetic,
        "unique_schedules": len(best),
        "unique_schedules_by_family": dict(sorted(families.items())),
        "usable_schedules": len(complete),
        "usable_schedules_by_family": dict(sorted(families_complete.items())),
        "rows_by_root_and_family": {
            root: dict(sorted(counter.items())) for root, counter in per_root.items()
        },
        "missing_count": len(missing),
        "missing_listed": missing[: args.max_missing_listed],
        "missing_truncated": max(0, len(missing) - args.max_missing_listed),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(payload, ensure_ascii=False, indent=1, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    print(f"строк манифеста: {payload['manifest_rows']}, статусы: {payload['manifest_statuses']}")
    print(f"уникальных расписаний: {payload['unique_schedules']}")
    print(f"из них с полным откликом на диске: {payload['usable_schedules']}")
    print("\nпо семействам (пригодные / всего):")
    for family in sorted(families):
        print(f"  {family:14} {families_complete.get(family, 0):>4} / {families[family]:<4}")
    if missing:
        print(f"\nнедостаёт откликов: {len(missing)}")
        for item in missing[: args.max_missing_listed]:
            print(f"  {item['family']:12} {item['scenario_id']:18} статус {item['status']}")
        if payload["missing_truncated"]:
            print(f"  … и ещё {payload['missing_truncated']}")
    print(f"\nотчёт: {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
