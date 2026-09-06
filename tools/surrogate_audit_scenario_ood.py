"""Audit a response-free blind feature cache with scenario-density OOD."""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path

import torch

from surrogate.scenario_ood import ScenarioDensityDomain


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--domain", type=Path, required=True)
    parser.add_argument("--blind-features", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    return parser


def _write_json(path: Path, payload: dict) -> None:
    if path.exists():
        raise FileExistsError(f"refusing to overwrite scenario OOD audit: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    temporary.replace(path)


def main() -> int:
    args = _parser().parse_args()
    domain = ScenarioDensityDomain.load(args.domain)
    blind = torch.load(args.blind_features, map_location="cpu", weights_only=False)
    if (
        blind.get("format") != "aios.surrogate-blind-npv-features.v1"
        or blind.get("response_data_read") is not False
        or blind.get("historical_test_read") is not False
        or blind.get("feature_set") != "full"
        or blind.get("dataset_hash") != domain.dataset_hash
    ):
        raise RuntimeError("blind scenario feature provenance differs")
    identities = blind["identities"]
    scores = domain.scores(blind["features"])
    if len(identities) != len(scores):
        raise RuntimeError("blind scenario identity/score counts differ")
    rows = [
        {
            **identity,
            "score": float(score),
            "inside": float(score) <= domain.threshold,
        }
        for identity, score in zip(identities, scores, strict=True)
    ]
    by_family = defaultdict(list)
    for row in rows:
        by_family[row["family"]].append(row)
    report = {
        "format": "aios.surrogate-scenario-density-blind-audit.v1",
        "response_data_read": False,
        "historical_test_read": False,
        "production_gate": False,
        "reason_not_production": (
            "hyperparameters were inspected on blind schedule-family labels; "
            "independent blind2 input audit is required"
        ),
        "plan_hash": blind["plan_hash"],
        "dataset_hash": domain.dataset_hash,
        "domain_version": domain.version,
        "threshold": domain.threshold,
        "n_scenarios": len(rows),
        "n_inside": sum(row["inside"] for row in rows),
        "n_outside": sum(not row["inside"] for row in rows),
        "by_family": {
            family: {
                "n": len(items),
                "inside": sum(item["inside"] for item in items),
                "outside": sum(not item["inside"] for item in items),
                "max_score": max(item["score"] for item in items),
            }
            for family, items in sorted(by_family.items())
        },
        "rows": rows,
    }
    _write_json(args.output, report)
    print(
        f"scenario density: inside={report['n_inside']}; outside={report['n_outside']}",
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
