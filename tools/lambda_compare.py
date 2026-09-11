from __future__ import annotations

import argparse
import json
import math
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping, Sequence

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from backend.core.contracts import Lambda
from backend.contexts.connectivity.application.campaign import CampaignError
from backend.contexts.connectivity.domain.measure import artifact_id, load_lambda_with_provenance


class LambdaCompareError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class EdgeOverlap:
    producers: tuple[str, ...]
    injectors: tuple[str, ...]
    left_values: tuple[float, ...]
    right_values: tuple[float, ...]
    left_only_edges: int
    right_only_edges: int
    left_total_edges: int
    right_total_edges: int


@dataclass(frozen=True, slots=True)
class ComparisonReport:
    left_path: str
    right_path: str
    left_artifact_id: str
    right_artifact_id: str
    left_shape: tuple[int, int]
    right_shape: tuple[int, int]
    left_window: tuple[str, str]
    right_window: tuple[str, str]
    left_lag_months: int
    right_lag_months: int
    lag_difference: int
    left_stability: float
    right_stability: float
    shared_producers: int
    shared_injectors: int
    shared_edges: int
    spearman: float
    sign_agreement: float
    left_only_edges: int
    right_only_edges: int
    left_provenance: dict[str, object]
    right_provenance: dict[str, object]

    def to_json(self) -> dict[str, object]:
        return {
            "left_path": self.left_path,
            "right_path": self.right_path,
            "left_artifact_id": self.left_artifact_id,
            "right_artifact_id": self.right_artifact_id,
            "left_shape": list(self.left_shape),
            "right_shape": list(self.right_shape),
            "left_window": list(self.left_window),
            "right_window": list(self.right_window),
            "left_lag_months": self.left_lag_months,
            "right_lag_months": self.right_lag_months,
            "lag_difference": self.lag_difference,
            "left_stability": self.left_stability,
            "right_stability": self.right_stability,
            "shared_producers": self.shared_producers,
            "shared_injectors": self.shared_injectors,
            "shared_edges": self.shared_edges,
            "spearman": self.spearman,
            "sign_agreement": self.sign_agreement,
            "left_only_edges": self.left_only_edges,
            "right_only_edges": self.right_only_edges,
            "left_provenance": self.left_provenance,
            "right_provenance": self.right_provenance,
        }


def average_ranks(values: Sequence[float]) -> tuple[float, ...]:
    if not values:
        raise LambdaCompareError(
            "ранжировать нечего: передан пустой набор значений"
        )
    order = sorted(range(len(values)), key=lambda index: values[index])
    ranks = [0.0] * len(values)
    position = 0
    while position < len(order):
        end = position
        while end + 1 < len(order) and values[order[end + 1]] == values[order[position]]:
            end += 1
        shared = (position + end) / 2.0 + 1.0
        for index in range(position, end + 1):
            ranks[order[index]] = shared
        position = end + 1
    return tuple(ranks)


def spearman(left: Sequence[float], right: Sequence[float]) -> float:
    if len(left) != len(right):
        raise LambdaCompareError(
            f"длины рядов расходятся: {len(left)} против {len(right)} — "
            f"ранговую корреляцию считать не по чему"
        )
    if len(left) < 2:
        raise LambdaCompareError(
            f"общих рёбер {len(left)}: ранговая корреляция определена от двух "
            f"наблюдений, на меньшем числе она не считается, а не равна нулю"
        )
    left_ranks = average_ranks(left)
    right_ranks = average_ranks(right)
    n = float(len(left_ranks))
    mean_left = sum(left_ranks) / n
    mean_right = sum(right_ranks) / n
    covariance = sum(
        (a - mean_left) * (b - mean_right) for a, b in zip(left_ranks, right_ranks)
    )
    variance_left = sum((a - mean_left) ** 2 for a in left_ranks)
    variance_right = sum((b - mean_right) ** 2 for b in right_ranks)
    if variance_left == 0.0 or variance_right == 0.0:
        raise LambdaCompareError(
            "один из рядов вырожден: все ранги совпали, корреляция не "
            "определена — выдавать за неё ноль нельзя"
        )
    return covariance / math.sqrt(variance_left * variance_right)


def sign_agreement(
    left: Sequence[float], right: Sequence[float], *, zero_tolerance: float
) -> float:
    if len(left) != len(right):
        raise LambdaCompareError(
            f"длины рядов расходятся: {len(left)} против {len(right)}"
        )
    if not left:
        raise LambdaCompareError(
            "общих рёбер нет: доля совпадающих знаков не определена"
        )

    def sign_of(value: float) -> int:
        if value > zero_tolerance:
            return 1
        if value < -zero_tolerance:
            return -1
        return 0

    matched = sum(
        1 for a, b in zip(left, right) if sign_of(a) == sign_of(b)
    )
    return matched / len(left)


def _cell_lookup(influence: Lambda) -> dict[tuple[str, str], float]:
    return {
        (producer, injector): influence.matrix[row][column]
        for row, producer in enumerate(influence.producers)
        for column, injector in enumerate(influence.injectors)
    }


def _nonzero_edges(influence: Lambda, zero_tolerance: float) -> set[tuple[str, str]]:
    return {
        key
        for key, value in _cell_lookup(influence).items()
        if abs(value) > zero_tolerance
    }


def overlap(left: Lambda, right: Lambda, *, zero_tolerance: float) -> EdgeOverlap:
    producers = tuple(sorted(set(left.producers) & set(right.producers)))
    injectors = tuple(sorted(set(left.injectors) & set(right.injectors)))
    if not producers or not injectors:
        raise LambdaCompareError(
            f"общая подматрица пуста: совпало добывающих {len(producers)}, "
            f"нагнетательных {len(injectors)} — сравнивать нечего, и нулевая "
            f"корреляция здесь была бы выдумкой, а не результатом"
        )
    left_cells = _cell_lookup(left)
    right_cells = _cell_lookup(right)
    left_values: list[float] = []
    right_values: list[float] = []
    for producer in producers:
        for injector in injectors:
            left_values.append(left_cells[(producer, injector)])
            right_values.append(right_cells[(producer, injector)])
    left_edges = _nonzero_edges(left, zero_tolerance)
    right_edges = _nonzero_edges(right, zero_tolerance)
    return EdgeOverlap(
        producers=producers,
        injectors=injectors,
        left_values=tuple(left_values),
        right_values=tuple(right_values),
        left_only_edges=len(left_edges - right_edges),
        right_only_edges=len(right_edges - left_edges),
        left_total_edges=len(left_edges),
        right_total_edges=len(right_edges),
    )


def _provenance_json(provenance: object) -> dict[str, object]:
    measured_at = getattr(provenance, "measured_at", None)
    source_run_ids = getattr(provenance, "source_run_ids", None)
    return {
        "artifact_id": getattr(provenance, "artifact_id", None),
        "measured_at": None if measured_at is None else measured_at.isoformat(),
        "n_runs": getattr(provenance, "n_runs", None),
        "source_run_ids": None if source_run_ids is None else list(source_run_ids),
        "code_version": getattr(provenance, "code_version", None),
        "missing_fields": list(getattr(provenance, "missing_fields", ())),
    }


def compare(
    left_path: Path, right_path: Path, *, zero_tolerance: float
) -> ComparisonReport:
    left, left_provenance = load_lambda_with_provenance(left_path)
    right, right_provenance = load_lambda_with_provenance(right_path)
    shared = overlap(left, right, zero_tolerance=zero_tolerance)
    return ComparisonReport(
        left_path=str(left_path),
        right_path=str(right_path),
        left_artifact_id=artifact_id(left),
        right_artifact_id=artifact_id(right),
        left_shape=(len(left.producers), len(left.injectors)),
        right_shape=(len(right.producers), len(right.injectors)),
        left_window=(left.window_start.isoformat(), left.window_end.isoformat()),
        right_window=(right.window_start.isoformat(), right.window_end.isoformat()),
        left_lag_months=left.lag_months,
        right_lag_months=right.lag_months,
        lag_difference=right.lag_months - left.lag_months,
        left_stability=left.stability,
        right_stability=right.stability,
        shared_producers=len(shared.producers),
        shared_injectors=len(shared.injectors),
        shared_edges=len(shared.left_values),
        spearman=spearman(shared.left_values, shared.right_values),
        sign_agreement=sign_agreement(
            shared.left_values, shared.right_values, zero_tolerance=zero_tolerance
        ),
        left_only_edges=shared.left_only_edges,
        right_only_edges=shared.right_only_edges,
        left_provenance=_provenance_json(left_provenance),
        right_provenance=_provenance_json(right_provenance),
    )


def _format_provenance(name: str, provenance: Mapping[str, object]) -> list[str]:
    lines = [f"  {name}:"]
    missing = provenance.get("missing_fields") or []
    for field in ("artifact_id", "measured_at", "n_runs", "code_version"):
        value = provenance.get(field)
        shown = "не записано" if value is None else str(value)
        lines.append(f"    {field:<16} {shown}")
    runs = provenance.get("source_run_ids")
    if runs is None:
        lines.append(f"    {'source_run_ids':<16} не записано")
    else:
        listed = list(runs)
        head = ", ".join(str(item) for item in listed[:3])
        tail = "" if len(listed) <= 3 else f" … и ещё {len(listed) - 3}"
        lines.append(f"    {'source_run_ids':<16} {head}{tail}")
    if missing:
        lines.append(
            f"    происхождение неполно, не записаны поля: "
            f"{', '.join(str(item) for item in missing)}"
        )
    return lines


def render(report: ComparisonReport) -> str:
    lines = [
        "=== два артефакта λ ===",
        f"  A  {report.left_path}",
        f"     окно {report.left_window[0]}…{report.left_window[1]}, "
        f"{report.left_shape[0]}×{report.left_shape[1]}, лаг "
        f"{report.left_lag_months} мес, устойчивость {report.left_stability:.4f}",
        f"     artifact_id (пересчитан) {report.left_artifact_id[:16]}…",
        f"  B  {report.right_path}",
        f"     окно {report.right_window[0]}…{report.right_window[1]}, "
        f"{report.right_shape[0]}×{report.right_shape[1]}, лаг "
        f"{report.right_lag_months} мес, устойчивость {report.right_stability:.4f}",
        f"     artifact_id (пересчитан) {report.right_artifact_id[:16]}…",
        "",
        "=== общая подматрица ===",
        f"  добывающих в обоих      {report.shared_producers}",
        f"  нагнетательных в обоих  {report.shared_injectors}",
        f"  общих ячеек             {report.shared_edges}",
        "",
        "=== согласие ===",
        f"  ранговая корреляция Спирмена  {report.spearman:+.4f}",
        f"  доля совпадающих знаков       {report.sign_agreement:.4f}",
        f"  различие лагов                {report.lag_difference:+d} мес "
        f"(A {report.left_lag_months}, B {report.right_lag_months})",
        "",
        "=== ненулевые рёбра ===",
        f"  только в A  {report.left_only_edges}",
        f"  только в B  {report.right_only_edges}",
        "",
        "=== происхождение ===",
    ]
    lines.extend(_format_provenance("A", report.left_provenance))
    lines.extend(_format_provenance("B", report.right_provenance))
    return "\n".join(lines)


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="lambda_compare",
        description=(
            "Сравнить два измеренных артефакта λ: общая подматрица, ранговая "
            "корреляция Спирмена, совпадение знаков, различие лагов, рёбра "
            "только в одном из артефактов."
        ),
    )
    parser.add_argument("left", type=Path)
    parser.add_argument("right", type=Path)
    parser.add_argument("--json", dest="json_out", type=Path, default=None)
    parser.add_argument("--zero-tolerance", type=float, default=0.0)
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        report = compare(
            args.left, args.right, zero_tolerance=args.zero_tolerance
        )
    except LambdaCompareError as error:
        print(f"сравнение не выполнено: {error}", flush=True)
        return 2
    except CampaignError as error:
        print(f"артефакт λ не прочитан: {error}", flush=True)
        return 3
    except (OSError, KeyError, ValueError) as error:
        print(f"артефакт не прочитан: {error}", flush=True)
        return 3
    print(render(report), flush=True)
    if args.json_out is not None:
        args.json_out.parent.mkdir(parents=True, exist_ok=True)
        args.json_out.write_text(
            json.dumps(report.to_json(), ensure_ascii=False, indent=2, sort_keys=True),
            encoding="utf-8",
        )
        print(f"\nотчёт записан: {args.json_out}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
