from __future__ import annotations

import argparse
import json
from pathlib import Path

from backend.core.contracts import (
    ChargeInitialEsp,
    DEFAULT_NORMATIVES_2007,
    NormativeSet,
    Policies,
    QuantizationPolicy,
)
from backend.domain.economics import (
    BalanceSheetInputs,
    ESP_CATALOG_2007,
    build_production_ledger,
    compute_npv_table,
    load_normatives,
)
from backend.domain.economics.reference_parity import compare_with_reference, run_reference

from .loader import load_example_input
from .paths import (
    chdd_python_dir,
    default_seed,
    example_input_xlsx,
    normatives_xlsx,
    require,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="aios npv",
        description="Расчёт ЧДД по Методике и сверка с эталонным расчётчиком организаторов.",
    )
    parser.add_argument("--out", type=Path, default=Path("/out"))
    parser.add_argument("--input", type=Path, default=None)
    parser.add_argument("--seed", type=int, default=default_seed())
    parser.add_argument("--no-reference", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    chdd_dir = require(chdd_python_dir(), "эталонный расчётчик CHDD_PYTHON")
    source = args.input if args.input is not None else example_input_xlsx()
    source = require(source, "входные данные (Пример_исходных_данных.xlsx)")

    workbook = normatives_xlsx()
    if workbook is not None:
        normatives = load_normatives(workbook)
        normatives_source = str(workbook)
    else:
        normatives = NormativeSet(
            **DEFAULT_NORMATIVES_2007, esp_catalog=ESP_CATALOG_2007
        )
        normatives_source = "DEFAULT_NORMATIVES_2007 (contracts)"

    policies = Policies(
        charge_initial_esp=ChargeInitialEsp.NOT_CHARGED,
        quantization_policy=QuantizationPolicy.NONE,
    )

    print(f"вход:      {source}")
    print(f"нормативы: {normatives_source}")
    print(f"seed:      {args.seed}")

    data = load_example_input(chdd_dir, source)
    print(f"скважин:   {data.n_wells}")
    print(f"интервалов:{data.n_intervals}")
    print(f"год начала:{data.start_year}")

    ledger = build_production_ledger(
        data.states_by_well,
        data.responses_by_well,
        data.interval_start_dates,
        normatives,
    )
    table = compute_npv_table(
        ledger,
        data.states_by_well,
        normatives,
        policies,
        BalanceSheetInputs(),
        discount_base_year=data.start_year,
    )

    print(f"\nnpv_methodology = {table.npv_methodology:.6f} руб")

    payload: dict[str, object] = {
        "npv_methodology": table.npv_methodology,
        "seed": args.seed,
        "input": str(source),
        "normatives_source": normatives_source,
        "n_wells": data.n_wells,
        "n_intervals": data.n_intervals,
        "start_year": data.start_year,
        "by_year": {
            str(year): table.by_year[year].discounted_fcf
            for year in sorted(table.by_year)
        },
    }

    if not args.no_reference:
        reference = run_reference(
            chdd_dir,
            data.records,
            normatives,
            policies,
            start_year=data.start_year,
        )
        report = compare_with_reference(
            table, reference, data.interval_start_dates
        )
        print(f"эталон          = {report.npv_reference:.6f} руб")
        print(f"расхождение     = {report.npv_absolute:.6e} руб")
        print(f"схождение       = {'ДА' if report.matched else 'НЕТ'}")
        payload["npv_reference"] = report.npv_reference
        payload["npv_absolute_difference"] = report.npv_absolute
        payload["matched"] = report.matched
        payload["discrepancies"] = len(report.discrepancies)

    args.out.mkdir(parents=True, exist_ok=True)
    destination = args.out / "npv.json"
    destination.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    print(f"\nзаписано: {destination}")

    if not args.no_reference and not payload.get("matched", True):
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
