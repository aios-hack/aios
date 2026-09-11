from __future__ import annotations

import json
import math
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

OUT = Path("data/g10-verification")
BASE_NPV = 11_873_676_459.64


def _ranks(values: list[float]) -> list[float]:
    order = sorted(range(len(values)), key=lambda i: values[i])
    ranks = [0.0] * len(values)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and values[order[j + 1]] == values[order[i]]:
            j += 1
        for k in range(i, j + 1):
            ranks[order[k]] = (i + j) / 2 + 1
        i = j + 1
    return ranks


def _pearson(x: list[float], y: list[float]) -> float:
    n = len(x)
    if n < 2:
        return float("nan")
    mx, my = sum(x) / n, sum(y) / n
    sx = math.sqrt(sum((v - mx) ** 2 for v in x))
    sy = math.sqrt(sum((v - my) ** 2 for v in y))
    if sx == 0.0 or sy == 0.0:
        return float("nan")
    return sum((a - mx) * (b - my) for a, b in zip(x, y)) / (sx * sy)


def main() -> int:
    rows = []
    for path in sorted(OUT.glob("candidate-*.json")):
        rows.append(json.loads(path.read_text(encoding="utf-8")))
    if not rows:
        print("not a single computed candidate", flush=True)
        return 1
    scored = [row for row in rows if row["actual_npv"] is not None]
    print(f"candidates computed {len(rows)}, with an issued NPV {len(scored)}")
    if not scored:
        return 1

    scored.sort(key=lambda row: -row["predicted_npv"])
    print("\n=== predicted against actual, bln RUB ===")
    print("  place  predicted     actual   error   violations  index")
    for place, row in enumerate(scored, start=1):
        predicted = row["predicted_npv"] / 1e9
        actual = row["actual_npv"] / 1e9
        print(
            f"  {place:5d}  {predicted:10.3f} {actual:8.3f} {predicted - actual:+8.3f} "
            f"{str(row['dynamic_violations']):>10}  {row['index']:5d}"
        )

    predicted = [row["predicted_npv"] for row in scored]
    actual = [row["actual_npv"] for row in scored]
    print(f"\nSpearman of predicted against actual: {_pearson(_ranks(predicted), _ranks(actual)):.4f}")
    print(f"Pearson:                            {_pearson(predicted, actual):.4f}")
    mae = sum(abs(p - a) for p, a in zip(predicted, actual)) / len(scored)
    bias = sum(p - a for p, a in zip(predicted, actual)) / len(scored)
    print(f"mean absolute error: {mae / 1e9:.3f} bln, bias {bias / 1e9:+.3f} bln")

    champion = max(scored, key=lambda row: row["actual_npv"])
    place = next(i for i, row in enumerate(scored, start=1) if row["index"] == champion["index"])
    print(
        f"\nchampion by real physics: candidate {champion['index']}, "
        f"actual {champion['actual_npv'] / 1e9:.3f} bln, "
        f"place in the predicted order {place} of {len(scored)}"
    )
    best_actual = champion["actual_npv"]
    print("\n=== regret@K: how much we lose by trusting the surrogate with a shortlist of K ===")
    print("  K   best actual in top-K   regret, mln RUB   champion inside")
    seen = float("-inf")
    for k in range(1, len(scored) + 1):
        seen = max(seen, scored[k - 1]["actual_npv"])
        regret = best_actual - seen
        inside = "yes" if regret == 0.0 else "no"
        if k <= 10 or regret == 0.0 or k == len(scored):
            print(f"  {k:2d}  {seen / 1e9:17.3f}   {regret / 1e6:14.1f}   {inside}")
        if regret == 0.0:
            break

    print(
        f"\nthe organizers' base schedule: {BASE_NPV / 1e9:.3f} bln; "
        f"our best candidate trails by {(BASE_NPV - best_actual) / 1e9:.3f} bln"
    )
    (OUT / "table.json").write_text(
        json.dumps(
            {
                "n_candidates": len(rows),
                "n_scored": len(scored),
                "spearman": _pearson(_ranks(predicted), _ranks(actual)),
                "pearson": _pearson(predicted, actual),
                "mae": mae,
                "bias": bias,
                "champion_index": champion["index"],
                "champion_actual_npv": best_actual,
                "champion_predicted_place": place,
                "npv_baseline": BASE_NPV,
                "rows": [
                    {
                        "index": row["index"],
                        "predicted_npv": row["predicted_npv"],
                        "actual_npv": row["actual_npv"],
                        "dynamic_violations": row["dynamic_violations"],
                        "canonical_schedule_hash": row["canonical_schedule_hash"],
                        "run_id": row["run_id"],
                    }
                    for row in scored
                ],
            },
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    print(f"\nwritten: {OUT / 'table.json'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
