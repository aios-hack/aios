"""Freeze corrected economic-target bytes for a response-free blind plan."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

if __package__:
    from tools.surrogate_build_npv_labels import _target_provenance
    from tools.surrogate_freeze_blind_protocol import _assert_response_free, _write
else:
    from surrogate_build_npv_labels import _target_provenance
    from surrogate_freeze_blind_protocol import _assert_response_free, _write


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset-root", type=Path, required=True)
    parser.add_argument("--model-dir", type=Path, required=True)
    parser.add_argument("--normatives", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    return parser


def main() -> int:
    args = _parser().parse_args()
    _assert_response_free(args.dataset_root)
    plan = json.loads((args.dataset_root / "plan.json").read_text(encoding="utf-8"))
    if (
        plan.get("n_scenarios") != 81
        or len(plan.get("scenarios", ())) != 81
        or not isinstance(plan.get("plan_hash"), str)
        or len(plan["plan_hash"]) != 64
    ):
        raise RuntimeError("blind economics lock requires a frozen 81-scenario plan")
    provenance = _target_provenance(
        project_root=Path(__file__).resolve().parents[1],
        model_schedule=args.model_dir / "Model_Z_sch.inc",
        normatives=args.normatives,
    )
    lock = {
        "format": "aios.surrogate-blind-economics-lock.v1",
        "historical_test_read": False,
        "response_data_read": False,
        "plan_hash": plan["plan_hash"],
        "source_sha256": provenance["source_sha256"],
        "methodology_version_hash": provenance["methodology_version_hash"],
        "model_schedule_sha256": provenance["model_schedule_sha256"],
        "normatives_sha256": provenance["normatives_sha256"],
        "target_provenance_sha256": provenance["target_provenance_sha256"],
    }
    _assert_response_free(args.dataset_root)
    final_provenance = _target_provenance(
        project_root=Path(__file__).resolve().parents[1],
        model_schedule=args.model_dir / "Model_Z_sch.inc",
        normatives=args.normatives,
    )
    if final_provenance != provenance:
        raise RuntimeError("economic target inputs changed during freeze")
    final_plan = json.loads(
        (args.dataset_root / "plan.json").read_text(encoding="utf-8")
    )
    if final_plan != plan:
        raise RuntimeError("blind plan changed during economics freeze")
    _write(args.output, lock)
    print(f"frozen blind economics written: {args.output}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
