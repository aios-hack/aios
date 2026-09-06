"""Freeze a disclosed-selected physical/direct blend into one NPV checkpoint."""

from __future__ import annotations

import argparse
import hashlib
import json
from dataclasses import replace
from pathlib import Path

from surrogate.ensemble import TrajectoryEnsemble
from surrogate.npv_block_head import (
    BlockKernelNpvHead,
    block_implementation_hash,
    load_direct_npv_head,
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--direct-head", type=Path, required=True)
    parser.add_argument("--ensemble", type=Path, required=True)
    parser.add_argument("--selection-audit", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    return parser


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _write_json(path: Path, payload: dict) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    temporary.replace(path)


def main() -> int:
    args = _parser().parse_args()
    checkpoint = args.output_dir / "npv_head.pt"
    report_path = args.output_dir / "blend_lock_report.json"
    if checkpoint.exists() or report_path.exists():
        raise FileExistsError(f"refusing to overwrite blend lock: {args.output_dir}")
    direct = load_direct_npv_head(args.direct_head)
    if not isinstance(direct, BlockKernelNpvHead):
        raise RuntimeError("physical blend requires a block NPV head")
    if direct.physical_npv_weight != 0.0:
        raise RuntimeError("direct head is already a physical blend")
    ensemble = TrajectoryEnsemble.load(args.ensemble)
    audit = json.loads(args.selection_audit.read_text(encoding="utf-8"))
    if (
        audit.get("format")
        != "aios.surrogate-disclosed-physical-blend-audit.v1"
        or audit.get("historical_test_read") is not False
        or audit.get("blind_responses_read_only_after_final_audits") is not True
    ):
        raise RuntimeError("physical blend selection audit is unsafe")
    selected = audit["selected"]
    weight = float(selected["physical_weight"])
    if (
        weight <= 0.0
        or weight >= 1.0
        or not selected.get("feasible_optimizer_gate_both_splits")
        or selected.get("worst_true_best_rank", 999) > 5
    ):
        raise RuntimeError("selected physical blend does not satisfy frozen gates")
    selection_hash = _sha256(args.selection_audit)
    candidate = replace(
        direct,
        implementation_hash=block_implementation_hash(),
        physical_npv_weight=weight,
        physical_ensemble_version=ensemble.version,
        physical_blend_provenance_hash=selection_hash,
        version="",
    )
    args.output_dir.mkdir(parents=True, exist_ok=True)
    candidate.save(checkpoint)
    loaded = load_direct_npv_head(checkpoint)
    if loaded.version != candidate.version:
        raise RuntimeError("saved physical blend failed round-trip")
    report = {
        "format": "aios.surrogate-physical-blend-lock.v1",
        "historical_test_read": False,
        "direct_head": str(args.direct_head),
        "direct_head_sha256": _sha256(args.direct_head),
        "direct_head_version": direct.version,
        "ensemble": str(args.ensemble),
        "ensemble_sha256": _sha256(args.ensemble),
        "ensemble_version": ensemble.version,
        "selection_audit": str(args.selection_audit),
        "selection_audit_sha256": selection_hash,
        "physical_npv_weight": weight,
        "direct_npv_weight": 1.0 - weight,
        "candidate_version": candidate.version,
        "checkpoint": str(checkpoint),
        "checkpoint_sha256": _sha256(checkpoint),
    }
    _write_json(report_path, report)
    print(
        f"locked physical blend {checkpoint}; version={candidate.version}",
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
