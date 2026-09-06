"""Generate a resumable compact OPM dataset reserved for blind evaluation."""

from __future__ import annotations

import argparse
import hashlib
import json
import threading
import time
from collections import Counter
from pathlib import Path

from bridge.cache import CachingOpmRunner, RunCache
from bridge.dataset import DatasetGenerator
from bridge.dataset_plan import PlanConfig, build_plan
from bridge.runner import OpmRunner
from tools.surrogate_freeze_blind_protocol import physical_pipeline_record


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model-dir", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--seed", type=int, default=20260827)
    parser.add_argument("--level-scenarios", type=int, default=45)
    parser.add_argument("--unreachable-scenarios", type=int, default=15)
    parser.add_argument("--shutdown-scenarios", type=int, default=15)
    parser.add_argument("--conversion-scenarios", type=int, default=5)
    parser.add_argument(
        "--workers",
        type=int,
        default=2,
        help="parallel Flow runs; 2 is the measured safe default for an 8 GiB VM",
    )
    parser.add_argument("--timeout-seconds", type=float, default=7200.0)
    parser.add_argument(
        "--opm-image",
        help="immutable image digest required by audited blind2 protocol",
    )
    parser.add_argument(
        "--protocol",
        type=Path,
        help="optional frozen protocol required for audited blind2 execution",
    )
    return parser


def _manifest_counts(path: Path) -> tuple[int, int]:
    latest = {}
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return 0, 0
    for line in lines:
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        latest[row.get("scenario_id")] = row.get("status")
    return sum(value == "OK" for value in latest.values()), sum(
        value != "OK" for value in latest.values()
    )


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    temporary.replace(path)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _validate_execution_protocol(
    protocol_path: Path,
    output_root: Path,
    *,
    plan_hash: str,
    count: int,
    model_dir: Path | None = None,
    opm_image: str | None = None,
) -> None:
    protocol = json.loads(protocol_path.read_text(encoding="utf-8"))
    frozen = protocol.get("plan", {})
    plan_path = output_root / "plan.json"
    audit_path = output_root / "plan_exclusion_audit.json"
    protocol_format = protocol.get("format")
    if (
        protocol_format
        not in {
            "aios.surrogate-blind-promotion-protocol.v1",
            "aios.surrogate-blind-promotion-protocol.v2",
        }
        or protocol.get("frozen_before_first_successful_blind_response") is not True
        or frozen.get("plan_hash") != plan_hash
        or frozen.get("expected_scenarios") != count
        or not plan_path.is_file()
        or frozen.get("plan_sha256") != _sha256(plan_path)
        or not audit_path.is_file()
        or frozen.get("exclusion_audit_sha256") != _sha256(audit_path)
    ):
        raise RuntimeError("execution plan differs from frozen blind protocol")
    if protocol_format == "aios.surrogate-blind-promotion-protocol.v2":
        if model_dir is None or protocol.get(
            "physical_pipeline"
        ) != physical_pipeline_record(model_dir, opm_image=opm_image):
            raise RuntimeError("physical pipeline differs from frozen blind protocol")


def main() -> int:
    args = _parser().parse_args()
    runner_factory = None
    if args.opm_image is not None:
        runner_factory = lambda root: CachingOpmRunner(
            OpmRunner(
                root / "runs",
                image=args.opm_image,
                timeout_seconds=args.timeout_seconds,
            ),
            RunCache(args.output_root / "cache"),
        )
    generator = DatasetGenerator(
        args.model_dir,
        args.output_root,
        max_workers=args.workers,
        timeout_seconds=args.timeout_seconds,
        load_responses=True,
        compact_artifacts=True,
        runner_factory=runner_factory,
    )
    config = PlanConfig(
        n_level_scenarios=args.level_scenarios,
        n_unreachable_scenarios=args.unreachable_scenarios,
        n_shutdown_scenarios=args.shutdown_scenarios,
        n_conversion_scenarios=args.conversion_scenarios,
    )
    plan = build_plan(generator.base_schedule(), seed=args.seed, config=config)
    target = len(plan.specs)
    if args.protocol is not None:
        _validate_execution_protocol(
            args.protocol,
            args.output_root,
            plan_hash=plan.plan_hash,
            count=target,
            model_dir=args.model_dir,
            opm_image=args.opm_image,
        )
    print(
        f"blind plan locked: seed={args.seed}; scenarios={target}; "
        f"plan_hash={plan.plan_hash}",
        flush=True,
    )
    stop = threading.Event()

    def monitor() -> None:
        while not stop.wait(30.0):
            successful, failed = _manifest_counts(
                args.output_root / "manifest.jsonl"
            )
            print(
                f"blind progress: OK={successful}/{target}; failed={failed}",
                flush=True,
            )

    watcher = threading.Thread(target=monitor, daemon=True)
    watcher.start()
    started = time.monotonic()
    try:
        report = generator.build(plan)
    finally:
        stop.set()
        watcher.join(timeout=2.0)
    payload = {
        "format": "aios.surrogate-blind-dataset.v1",
        "purpose": "locked comparison after model selection",
        "seed": args.seed,
        "plan_hash": report.plan_hash,
        "dataset_hash": report.dataset_hash,
        "n_scenarios": len(report.samples),
        "n_failed": len(report.failed),
        "n_skipped": len(report.skipped),
        "n_from_cache": report.n_from_cache,
        "families": dict(Counter(item.metadata.family.value for item in report.samples)),
        "scenario_identity": [
            {
                "scenario_id": item.metadata.scenario_id,
                "family": item.metadata.family.value,
                "canonical_schedule_hash": item.metadata.canonical_schedule_hash,
                "response_hash": item.metadata.response_hash,
                "run_id": item.metadata.run_id,
            }
            for item in report.samples
        ],
        "seconds": time.monotonic() - started,
    }
    complete = not report.failed and not report.skipped and len(report.samples) == target
    report_name = "blind_report.json" if complete else "blind_report.incomplete.json"
    _write_json(args.output_root / report_name, payload)
    if not complete:
        raise RuntimeError(
            f"blind dataset incomplete: samples={len(report.samples)}/{target}; "
            f"failed={len(report.failed)}; skipped={len(report.skipped)}"
        )
    print(
        f"blind complete: {len(report.samples)} scenarios; "
        f"dataset_hash={report.dataset_hash}",
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
