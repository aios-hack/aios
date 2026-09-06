"""Пакет сдачи из проверенного OPM кандидата — требование ТЗ §6.6.

Организаторы выполняют **один расчёт полной ГГДМ** и сравнивают полученный ЧДД
с заявленным; расхождение сверх пары процентов — дисквалификация, повторных
попыток нет. Поэтому заявляемое число берётся только из собственного прогона
OPM ровно того расписания, которое сдаётся, и собирается сюда вместе со всеми
хешами, по которым это можно проверить.

Кандидат допускается к сдаче, только если он:

* прошёл полный submission-тракт (эмиссия дека, Flow, разбор отклика,
  эталонная экономика);
* не имеет **блокирующих** динамических нарушений;
* даёт ЧДД выше проверенного incumbent.

Последнее — не формальность. На G10 все 40 кандидатов были хуже эталона на
1.036 млрд, и протокол всё равно вернул максимум прогноза: сравнения с опорой
в нём не было. Здесь incumbent — сам эталон организаторов, и кандидат, не
бьющий его, в пакет не попадает.

Запуск:

    PYTHONPATH=. python tools/build_submission.py \\
        --runs data/anchor-doe-feasible --incumbent anchor --out out/submission
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from contracts import hash_schedule
from schedule import BLOCKING_DYNAMIC_VIOLATION_KINDS, canonicalize
from schedule.build import load_schedule

FORMAT = "aios.submission.v1"
SCHEDULE_INCLUDE = "Model_Z_sch.inc"
BLOCKING = frozenset(kind.value for kind in BLOCKING_DYNAMIC_VIOLATION_KINDS)


class SubmissionError(RuntimeError):
    pass


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runs", type=Path, required=True)
    parser.add_argument(
        "--incumbent",
        default="anchor",
        help="имя прогона-опоры: кандидат обязан его превзойти",
    )
    parser.add_argument("--out", type=Path, required=True)
    return parser


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def _blocking(row: dict) -> int:
    return sum(
        count
        for kind, count in (row.get("violations_by_kind") or {}).items()
        if kind in BLOCKING
    )


def main() -> int:
    args = _parser().parse_args()
    rows = [
        json.loads(path.read_text(encoding="utf-8"))
        for path in sorted(args.runs.glob("*/result.json"))
    ]
    if not rows:
        raise SubmissionError(f"{args.runs}: прогонов не найдено")
    by_name = {row["name"]: row for row in rows}
    incumbent = by_name.get(args.incumbent)
    if incumbent is None:
        raise SubmissionError(f"опора {args.incumbent!r} отсутствует среди прогонов")
    if incumbent.get("npv_rub") is None:
        raise SubmissionError("у опоры нет ЧДД: без него сравнивать не с чем")

    print(f"{'кандидат':28} {'ЧДД,млрд':>9} {'Δ,млн':>8} {'блок':>5} допуск")
    admissible = []
    for row in sorted(rows, key=lambda item: -(item.get("npv_rub") or 0.0)):
        npv = row.get("npv_rub")
        if npv is None:
            print(f"{row['name']:28} {'—':>9} {'—':>8} {'—':>5} нет отклика")
            continue
        blocking = _blocking(row)
        delta = npv - incumbent["npv_rub"]
        if row["name"] == args.incumbent:
            verdict = "опора"
        elif blocking:
            verdict = f"отклонён: {blocking} блокирующих"
        elif delta <= 0.0:
            verdict = "отклонён: не бьёт опору"
        else:
            verdict = "допущен"
            admissible.append((npv, row))
        print(
            f"{row['name']:28} {npv/1e9:>9.4f} {delta/1e6:>+8.1f} {blocking:>5} {verdict}"
        )

    if not admissible:
        print(
            "\nДопустимого кандидата лучше опоры нет. Сдаётся опора — это "
            "правильный исход протокола, а не сбой: incumbent остаётся тем, "
            "что проверено.",
            flush=True,
        )
        chosen = incumbent
        improvement = 0.0
    else:
        _, chosen = max(admissible, key=lambda item: item[0])
        improvement = chosen["npv_rub"] - incumbent["npv_rub"]

    deck = args.runs / chosen["name"] / "work" / "deck" / SCHEDULE_INCLUDE
    if not deck.is_file():
        raise SubmissionError(f"эмитированное расписание не найдено: {deck}")

    args.out.mkdir(parents=True, exist_ok=True)
    target = args.out / "wells_schedule.inc"
    shutil.copy2(deck, target)

    # Что реально лежит в сдаваемом файле. Эмиссия и обратный разбор сегодня
    # не полностью обратимы: на самом эталоне организаторов теряются 20
    # событий — десять пар (SET_LRAT 0.0, OPEN) на скважинах в момент перевода
    # под закачку, и канонический хеш меняется. Физический смысл, судя по
    # совпадению ЧДД, сохраняется: «открыть добывающую с нулевым дебитом»
    # эквивалентно закрытой, а OPM считал именно этот файл. Но заявлять хеш
    # объекта в памяти, которого в файле нет, нельзя — манифест несёт оба и
    # называет расхождение.
    reparsed = canonicalize(load_schedule(target))
    file_hash = hash_schedule(reparsed)
    lossless = file_hash == chosen["canonical_schedule_hash"]

    manifest = {
        "format": FORMAT,
        "canonical_schedule_hash_of_emitted_file": file_hash,
        "emit_parse_round_trip_lossless": lossless,
        "selected_run": chosen["name"],
        "claimed_npv_rub": chosen["npv_rub"],
        "claimed_npv_bln_rub": chosen["npv_rub"] / 1e9,
        "incumbent_run": args.incumbent,
        "incumbent_npv_rub": incumbent["npv_rub"],
        "improvement_rub": improvement,
        "improvement_mln_rub": improvement / 1e6,
        "canonical_schedule_hash": chosen["canonical_schedule_hash"],
        "opm_run_id": chosen.get("opm_run_id"),
        "response_hash": chosen.get("response_hash"),
        "wells_schedule_sha256": _sha256(target),
        "dynamic_violations_total": chosen.get("n_dynamic_violations"),
        "dynamic_violations_by_kind": chosen.get("violations_by_kind"),
        "blocking_violations": _blocking(chosen),
        # Заявляемое число приходит из прогона OPM этого же расписания, а не
        # из суррогата: суррогат ранжирует кандидатов, число даёт симулятор.
        "npv_source": "own OPM run of this exact schedule",
    }
    (args.out / "claimed_npv.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=1, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    print(f"\nсдаётся: {chosen['name']}")
    print(f"  заявляемый ЧДД: {chosen['npv_rub']/1e9:.4f} млрд ₽")
    print(f"  прирост к опоре: {improvement/1e6:+.1f} млн ₽")
    print(f"  блокирующих нарушений: {_blocking(chosen)}")
    print(f"  расписание: {target}")
    print(f"  манифест:   {args.out / 'claimed_npv.json'}")
    if not lossless:
        print(
            "\nВНИМАНИЕ: emit→parse не обратим. Хеш расписания в памяти "
            f"{chosen['canonical_schedule_hash'][:16]}…, хеш разобранного файла "
            f"{file_hash[:16]}…. Тот же разрыв воспроизводится на самом эталоне "
            "организаторов, то есть это свойство тракта, а не этого кандидата. "
            "ЧДД заявляется по прогону OPM именно этого файла, оба хеша в "
            "манифесте.",
            flush=True,
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
