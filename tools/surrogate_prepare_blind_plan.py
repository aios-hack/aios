"""Prepare an untouched blind plan and reject overlap with training schedules."""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from pathlib import Path
from typing import Any

import torch

from bridge.dataset_plan import (
    PlanConfig,
    PerturbationFamily,
    build_plan,
    dataset_base_schedule,
    materialize,
)
from bridge.opm_deck import OpmDeckEmitter
from contracts import hash_schedule

if __package__:
    from tools.surrogate_freeze_blind_protocol import _assert_response_free, _write
else:
    from surrogate_freeze_blind_protocol import _assert_response_free, _write


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model-dir", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--seed", type=int, required=True)
    parser.add_argument(
        "--exclude-identities",
        type=Path,
        action="append",
        required=True,
        help="response-free .pt cache or JSON report whose schedule hashes are training",
    )
    parser.add_argument("--level-scenarios", type=int, default=45)
    parser.add_argument("--unreachable-scenarios", type=int, default=15)
    parser.add_argument("--shutdown-scenarios", type=int, default=15)
    parser.add_argument("--conversion-scenarios", type=int, default=5)
    return parser


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_generator_compatible_plan(path: Path, payload: dict[str, Any]) -> None:
    """Match DatasetGenerator._write_plan bytes so execution cannot change SHA."""

    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    temporary.replace(path)


def _identity_rows(path: Path) -> list[dict[str, Any]]:
    if path.suffix == ".pt":
        payload = torch.load(path, map_location="cpu", weights_only=False)
        if (
            payload.get("historical_test_read") is not False
            or payload.get("response_data_read") is not False
        ):
            raise RuntimeError(
                f"unsafe exclusion cache may contain response/test data: {path}"
            )
        rows = payload.get("identities")
    else:
        payload = json.loads(path.read_text(encoding="utf-8"))
        rows = payload.get("scenario_identity", payload.get("rows"))
        if isinstance(rows, dict):
            rows = list(rows.values())
    if not isinstance(rows, list) or not rows:
        raise RuntimeError(f"exclusion identities are missing: {path}")
    for row in rows:
        schedule_hash = row.get("canonical_schedule_hash")
        if not isinstance(schedule_hash, str) or len(schedule_hash) != 64:
            raise RuntimeError(f"invalid exclusion schedule hash: {path}")
    return rows


def main() -> int:
    args = _parser().parse_args()
    args.output_root.mkdir(parents=True, exist_ok=True)
    _assert_response_free(args.output_root)
    plan_path = args.output_root / "plan.json"
    audit_path = args.output_root / "plan_exclusion_audit.json"
    if plan_path.exists() or audit_path.exists():
        raise FileExistsError("refusing to overwrite a frozen blind plan")
    exclusions: set[str] = set()
    exclusion_artifacts = []
    for path in args.exclude_identities:
        rows = _identity_rows(path)
        exclusions.update(row["canonical_schedule_hash"] for row in rows)
        exclusion_artifacts.append(
            {"path": str(path), "sha256": _sha256(path), "rows": len(rows)}
        )
    row_counts = sorted(item["rows"] for item in exclusion_artifacts)
    if (
        len(row_counts) < 2
        or row_counts[-1] != 595
        or any(item != 81 for item in row_counts[:-1])
    ):
        raise RuntimeError(
            "blind exclusions must be one historical-595 cache plus disclosed-81 caches"
        )
    disclosed_blinds = len(row_counts) - 1
    expected_unique = 593 + 80 * disclosed_blinds
    if len(exclusions) != expected_unique:
        raise RuntimeError(
            f"expected {expected_unique} unique disclosed training schedules, "
            f"got {len(exclusions)}"
        )
    emitter = OpmDeckEmitter(args.model_dir)
    base = dataset_base_schedule(args.model_dir, emitter)
    config = PlanConfig(
        n_level_scenarios=args.level_scenarios,
        n_unreachable_scenarios=args.unreachable_scenarios,
        n_shutdown_scenarios=args.shutdown_scenarios,
        n_conversion_scenarios=args.conversion_scenarios,
    )
    plan = build_plan(base, seed=args.seed, config=config)
    if len(plan.specs) != 81:
        raise RuntimeError(f"blind plan must contain 81 scenarios, got {len(plan.specs)}")
    seen: set[str] = set()
    baseline_overlaps = []
    for spec in plan.specs:
        schedule_hash = hash_schedule(materialize(base, spec).schedule)
        if schedule_hash in seen:
            raise RuntimeError(f"blind plan contains duplicate schedule: {spec.scenario_id}")
        seen.add(schedule_hash)
        if schedule_hash not in exclusions:
            continue
        if spec.family is PerturbationFamily.BASELINE:
            baseline_overlaps.append(spec.scenario_id)
            continue
        raise RuntimeError(f"blind plan overlaps training schedule: {spec.scenario_id}")
    payload = {
        "plan_hash": plan.plan_hash,
        "seed": plan.seed,
        "n_scenarios": len(plan),
        "families": sorted(family.value for family in plan.families()),
        "scenarios": [
            {
                "scenario_id": spec.scenario_id,
                "family": spec.family.value,
                "seed": spec.seed,
                "spec_hash": spec.spec_hash,
            }
            for spec in plan
        ],
    }
    audit = {
        "format": "aios.surrogate-blind-plan-exclusion-audit.v1",
        "plan_hash": plan.plan_hash,
        "plan_seed": plan.seed,
        "n_scenarios": len(plan),
        "family_counts": dict(Counter(spec.family.value for spec in plan.specs)),
        "excluded_unique_schedule_count": len(exclusions),
        "exclusion_artifacts": exclusion_artifacts,
        "nonbaseline_overlap_count": 0,
        "allowed_baseline_overlaps": baseline_overlaps,
        "historical_test_read": False,
        "response_data_read": False,
    }
    _assert_response_free(args.output_root)
    _write_generator_compatible_plan(plan_path, payload)
    _write(audit_path, audit)
    print(
        f"untouched blind plan written: seed={plan.seed}; hash={plan.plan_hash}",
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
