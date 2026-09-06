"""Recompute NPV labels only after a blind dataset's final disclosure audit."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
from typing import Any

if __package__:
    from tools.surrogate_build_npv_labels import _target_provenance
    from tools.surrogate_evaluate_blind_npv import _plan_from_artifact
    from tools.surrogate_evaluate_ensemble_npv import _cache_index
else:
    from surrogate_build_npv_labels import _target_provenance
    from surrogate_evaluate_blind_npv import _plan_from_artifact
    from surrogate_evaluate_ensemble_npv import _cache_index

from bridge.dataset_plan import materialize
from bridge.opm_deck import OpmDeckEmitter
from bridge.response_loader import ResponseLoader, load_density_by_pvtnum
from bridge.summary import build_summary_plan
from config.schema import default_policies
from contracts import hash_schedule
from economics import analyze_base_case, load_normatives
from schedule import parse_schedule


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model-dir", type=Path, required=True)
    parser.add_argument("--dataset-root", type=Path, required=True)
    parser.add_argument("--blind-report", type=Path, required=True)
    parser.add_argument("--comparison", type=Path, required=True)
    parser.add_argument("--decision", type=Path, required=True)
    parser.add_argument("--final-audit", type=Path, required=True)
    parser.add_argument("--normatives", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    return parser


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _write(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    temporary.replace(path)


def _validate_disclosure(
    blind: dict[str, Any],
    comparison: dict[str, Any],
    final_audit: dict[str, Any],
    *,
    blind_sha256: str,
    comparison_sha256: str,
    decision_sha256: str,
) -> None:
    if (
        blind.get("format") != "aios.surrogate-blind-dataset.v1"
        or blind.get("n_scenarios") != 81
        or blind.get("n_failed") != 0
        or blind.get("n_skipped") != 0
        or len(blind.get("scenario_identity", ())) != 81
    ):
        raise RuntimeError("blind dataset is not complete")
    if (
        comparison.get("format") != "aios.surrogate-blind-npv-comparison.v1"
        or comparison.get("blind_report_sha256") != blind_sha256
        or comparison.get("raw_row_count") != 81
    ):
        raise RuntimeError("blind comparison does not disclose the complete dataset")
    if (
        final_audit.get("format") != "aios.surrogate-blind-final-audit.v1"
        or final_audit.get("all_checks_pass") is not True
        or final_audit.get("blind_report_sha256") != blind_sha256
        or final_audit.get("comparison_sha256") != comparison_sha256
        or final_audit.get("decision_sha256") != decision_sha256
    ):
        raise RuntimeError("blind final disclosure audit differs")


def _validate_disclosed_rows(
    rows: object,
    identities: dict[str, dict[str, Any]],
    comparison_rows: dict[str, dict[str, Any]],
    *,
    require_complete: bool,
) -> None:
    if not isinstance(rows, dict) or not set(rows) <= set(identities):
        raise RuntimeError("disclosed labels contain unexpected rows")
    for scenario_id, row in rows.items():
        identity = identities[scenario_id]
        comparison = comparison_rows[scenario_id]
        if not isinstance(row, dict) or any(
            row.get(field) != expected
            for field, expected in (
                ("scenario_id", scenario_id),
                ("family", identity.get("family")),
                (
                    "canonical_schedule_hash",
                    identity.get("canonical_schedule_hash"),
                ),
                ("response_hash", identity.get("response_hash")),
            )
        ):
            raise RuntimeError(f"{scenario_id}: resumed disclosed identity differs")
        if row["response_hash"] != comparison.get("response_hash"):
            raise RuntimeError(f"{scenario_id}: resumed response hash differs")
        npv = row.get("npv_rub")
        if type(npv) not in (int, float) or not math.isfinite(float(npv)):
            raise RuntimeError(f"{scenario_id}: resumed disclosed NPV is invalid")
    if require_complete and set(rows) != set(identities):
        raise RuntimeError("disclosed label population is incomplete")


def main() -> int:
    args = _parser().parse_args()
    blind = json.loads(args.blind_report.read_text(encoding="utf-8"))
    comparison = json.loads(args.comparison.read_text(encoding="utf-8"))
    final_audit = json.loads(args.final_audit.read_text(encoding="utf-8"))
    blind_sha256 = _sha256(args.blind_report)
    comparison_sha256 = _sha256(args.comparison)
    decision_sha256 = _sha256(args.decision)
    _validate_disclosure(
        blind,
        comparison,
        final_audit,
        blind_sha256=blind_sha256,
        comparison_sha256=comparison_sha256,
        decision_sha256=decision_sha256,
    )
    _, base, plan = _plan_from_artifact(args.model_dir, args.dataset_root)
    if plan.plan_hash != blind.get("plan_hash"):
        raise RuntimeError("blind report/plan hashes differ")
    identities = {item["scenario_id"]: item for item in blind["scenario_identity"]}
    comparison_rows = {item["scenario_id"]: item for item in comparison["rows"]}
    expected_ids = {item.scenario_id for item in plan.specs}
    if set(identities) != expected_ids or set(comparison_rows) != expected_ids:
        raise RuntimeError("blind identity populations differ")

    model_schedule = args.model_dir / "Model_Z_sch.inc"
    provenance = _target_provenance(
        project_root=Path(__file__).resolve().parents[1],
        model_schedule=model_schedule,
        normatives=args.normatives,
    )
    metadata = {
        "format": "aios.surrogate-disclosed-blind-npv-labels.v1",
        "historical_test_read": False,
        "blind_response_read_after_final_audit": True,
        "fit_population_role": "augmentation_after_frozen_hyperparameter_selection",
        "plan_hash": plan.plan_hash,
        "blind_dataset_hash": blind["dataset_hash"],
        "blind_report_sha256": blind_sha256,
        "comparison_sha256": comparison_sha256,
        "decision_sha256": decision_sha256,
        "final_audit_sha256": _sha256(args.final_audit),
        "target_provenance": provenance,
        "expected_rows": 81,
    }
    payload = (
        json.loads(args.output.read_text(encoding="utf-8"))
        if args.output.exists()
        else {**metadata, "rows": {}}
    )
    for key, value in metadata.items():
        if payload.get(key) != value:
            raise RuntimeError(f"disclosed labels resume provenance differs: {key}")
    _validate_disclosed_rows(
        payload.get("rows"),
        identities,
        comparison_rows,
        require_complete=False,
    )

    emitter = OpmDeckEmitter(args.model_dir)
    summary_plan = build_summary_plan(args.model_dir, emitter.source_wells)
    densities = load_density_by_pvtnum(args.model_dir)
    response_loader = ResponseLoader()
    cache = _cache_index(args.dataset_root)
    parsed = parse_schedule(model_schedule.read_bytes())
    normatives = load_normatives(args.normatives)
    policies = default_policies()
    pending = [
        spec
        for spec in sorted(plan.specs, key=lambda item: item.scenario_id)
        if spec.scenario_id not in payload["rows"]
    ]
    for index, spec in enumerate(pending, start=1):
        material = materialize(base, spec)
        identity = identities[spec.scenario_id]
        schedule_hash = hash_schedule(material.schedule)
        if schedule_hash != identity["canonical_schedule_hash"]:
            raise RuntimeError(f"{spec.scenario_id}: disclosed schedule hash differs")
        run = cache.get(schedule_hash)
        if run is None:
            raise RuntimeError(
                f"{spec.scenario_id}: disclosed response cache is missing"
            )
        response = response_loader.load(run, summary_plan, material.schedule, densities)
        if not (
            response.response_hash
            == identity["response_hash"]
            == comparison_rows[spec.scenario_id]["response_hash"]
        ):
            raise RuntimeError(f"{spec.scenario_id}: disclosed response hash differs")
        npv = analyze_base_case(
            response,
            parsed.dates,
            parsed.t0_deck_date_index,
            normatives,
            policies,
        ).npv_methodology
        payload["rows"][spec.scenario_id] = {
            "scenario_id": spec.scenario_id,
            "family": spec.family.value,
            "canonical_schedule_hash": schedule_hash,
            "response_hash": response.response_hash,
            "npv_rub": npv,
        }
        _write(args.output, payload)
        if index == 1 or index % 10 == 0 or index == len(pending):
            print(f"corrected disclosed labels {len(payload['rows'])}/81", flush=True)
    _validate_disclosed_rows(
        payload["rows"], identities, comparison_rows, require_complete=True
    )
    if (
        _target_provenance(
            project_root=Path(__file__).resolve().parents[1],
            model_schedule=model_schedule,
            normatives=args.normatives,
        )
        != provenance
    ):
        raise RuntimeError("target provenance changed during disclosed label build")
    print(f"disclosed blind labels written: {args.output}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
