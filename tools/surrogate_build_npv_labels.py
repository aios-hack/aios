"""Build exact per-scenario NPV labels from cached OPM responses only."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import time
from pathlib import Path

from bridge.cache import RunCache
from bridge.dataset import DatasetGenerator
from bridge.dataset_plan import baseline_profile, build_plan, materialize
from bridge.opm_deck import OpmDeckEmitter
from bridge.response_loader import ResponseLoader, load_density_by_pvtnum
from bridge.summary import build_summary_plan
from config.schema import default_policies
from contracts import RunStatus, canonical_bytes
from economics import analyze_base_case, load_normatives, methodology_version_hash
from schedule import parse_schedule
from surrogate.cycle import EXTRA_CONFIG, PILOT_CONFIG
from surrogate.npv_target import TARGET_PROVENANCE_FORMAT, TARGET_SOURCE_FILES

SPLIT_BUCKETS = ("train", "validation", "test")
EXPECTED_BUCKET_COUNTS = {"train": 490, "validation": 105, "test": 105}
DATASETS = (
    ("dataset-main", 20260816, PILOT_CONFIG),
    ("dataset-extra-500", 20260817, EXTRA_CONFIG),
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model-dir", type=Path, required=True)
    parser.add_argument("--data-root", type=Path, required=True)
    parser.add_argument("--split-report", type=Path, required=True)
    parser.add_argument("--normatives", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--buckets",
        nargs="+",
        choices=SPLIT_BUCKETS,
        required=True,
        help="explicit label population; v4 selection must use train validation",
    )
    parser.add_argument("--batch-size", type=int, default=25)
    return parser


def _save(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    temporary.replace(path)


def _material_contexts(
    model_dir: Path,
    data_root: Path,
    expected: list[tuple[str, dict]],
) -> dict[str, tuple[object, object, dict[str, object]]]:
    """Prepare deterministic plans once; materialize only the active batch."""

    wanted = {
        (identity["source_dataset"], identity["scenario_id"]): identity
        for _, identity in expected
    }
    result = {}
    for source, seed, config in DATASETS:
        generator = DatasetGenerator(
            model_dir,
            data_root / source,
            max_workers=1,
            timeout_seconds=1.0,
            compact_artifacts=False,
            load_responses=False,
        )
        base = generator.base_schedule()
        profile = baseline_profile(base)
        specs: dict[str, object] = {
            spec.scenario_id: spec
            for spec in build_plan(base, seed=seed, config=config)
        }
        selected = [
            (key, identity)
            for key, identity in wanted.items()
            if key[0] == source
        ]
        missing = [key[1] for key, _ in selected if key[1] not in specs]
        if missing:
            raise RuntimeError(f"{source}: scenarios are absent from plan: {missing}")
        result[source] = (base, profile, specs)
    return result


def _cache_index(data_root: Path) -> dict[tuple[str, str], dict]:
    """Index cache metadata only; no simulator response is opened here."""

    result = {}
    for source, _, _ in DATASETS:
        cache_root = data_root / source / "cache"
        if not cache_root.is_dir():
            raise RuntimeError(f"missing dataset cache: {cache_root}")
        for path in sorted(cache_root.glob("*.json")):
            try:
                row = json.loads(path.read_text(encoding="utf-8"))
            except json.JSONDecodeError as error:
                raise RuntimeError(f"{path}: invalid cache JSON") from error
            schedule_hash = row.get("canonical_schedule_hash")
            if row.get("status") != RunStatus.OK.value or not isinstance(
                schedule_hash, str
            ):
                continue
            key = (source, schedule_hash)
            previous = result.get(key)
            if previous is not None and any(
                previous.get(field) != row.get(field)
                for field in ("deck_hash", "summary_hash", "artifacts")
            ):
                raise RuntimeError(f"{source}:{schedule_hash}: ambiguous cache entries")
            result[key] = row
    return result


def _load_cached_responses(
    identities: list[dict],
    *,
    material_contexts: dict[str, tuple[object, object, dict[str, object]]],
    cache_records: dict[tuple[str, str], dict],
    caches: dict[str, RunCache],
    loader: ResponseLoader,
    summary_plan: object,
    densities: dict[int, float],
) -> tuple[object, ...]:
    responses = []
    for identity in identities:
        key = (identity["source_dataset"], identity["scenario_id"])
        schedule_hash = identity["canonical_schedule_hash"]
        row = cache_records.get((key[0], schedule_hash))
        if row is None:
            raise RuntimeError(f"{key[0]}:{key[1]}: exact schedule cache row missing")
        run = caches[key[0]].lookup(
            row.get("deck_hash", ""),
            schedule_hash,
            row.get("summary_hash", ""),
        )
        if run is None or run.status is not RunStatus.OK:
            raise RuntimeError(f"{key[0]}:{key[1]}: cached OPM result missing")
        base, profile, specs = material_contexts[key[0]]
        material = materialize(base, specs[key[1]], profile=profile)
        response = loader.load(
            run,
            summary_plan,
            material.schedule,
            densities,
        )
        responses.append(response)
    return tuple(responses)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _selected_identities(
    training: dict, buckets: tuple[str, ...]
) -> list[tuple[str, dict]]:
    if not buckets or len(set(buckets)) != len(buckets):
        raise ValueError("buckets must be a non-empty unique sequence")
    if not set(buckets) <= set(SPLIT_BUCKETS):
        raise ValueError(
            f"unsupported buckets: {sorted(set(buckets) - set(SPLIT_BUCKETS))}"
        )
    identities = training.get("split_identity")
    if not isinstance(identities, dict) or not set(SPLIT_BUCKETS) <= set(identities):
        raise RuntimeError("split report does not contain all canonical buckets")
    complete = [
        (bucket, item) for bucket in SPLIT_BUCKETS for item in identities[bucket]
    ]
    if len(complete) != 700:
        raise RuntimeError(f"expected 700 split identities, got {len(complete)}")
    for bucket, count in EXPECTED_BUCKET_COUNTS.items():
        if len(identities[bucket]) != count:
            raise RuntimeError(f"unexpected {bucket} split size: {len(identities[bucket])}")
    keys = [
        (item.get("source_dataset"), item.get("scenario_id"))
        for _, item in complete
    ]
    if any(not all(isinstance(value, str) and value for value in key) for key in keys):
        raise RuntimeError("split identities are incomplete")
    if len(set(keys)) != len(keys):
        raise RuntimeError("split identities are not unique")
    return [(bucket, item) for bucket in buckets for item in identities[bucket]]


def _validate_label_rows(payload: dict, expected: list[tuple[str, dict]]) -> None:
    rows = payload.get("rows")
    if not isinstance(rows, dict):
        raise RuntimeError("labels rows must be an object")
    expected_by_key = {
        f"{item['source_dataset']}:{item['scenario_id']}": (bucket, item)
        for bucket, item in expected
    }
    if len(expected_by_key) != len(expected):
        raise RuntimeError("selected label identities are not unique")
    if not set(rows) <= set(expected_by_key):
        raise RuntimeError("labels contain rows outside explicitly selected buckets")
    for key, row in rows.items():
        bucket, identity = expected_by_key[key]
        if not isinstance(row, dict) or any(
            row.get(field) != identity.get(field)
            for field in (
                "source_dataset",
                "scenario_id",
                "canonical_schedule_hash",
            )
        ) or row.get("bucket") != bucket:
            raise RuntimeError(f"{key}: resumed label identity differs")
        npv = row.get("npv_rub")
        response_hash = row.get("response_hash")
        if type(npv) not in (int, float) or not math.isfinite(float(npv)):
            raise RuntimeError(f"{key}: resumed NPV is invalid")
        if (
            not isinstance(response_hash, str)
            or len(response_hash) != 64
            or any(character not in "0123456789abcdef" for character in response_hash)
        ):
            raise RuntimeError(f"{key}: resumed response hash is invalid")


def _target_provenance(
    *, project_root: Path, model_schedule: Path, normatives: Path
) -> dict[str, object]:
    payload: dict[str, object] = {
        "format": TARGET_PROVENANCE_FORMAT,
        "target": "npv_methodology_rub",
        "methodology_version_hash": methodology_version_hash(),
        "source_sha256": {
            relative: _sha256(project_root / relative)
            for relative in TARGET_SOURCE_FILES
        },
        "model_schedule_sha256": _sha256(model_schedule),
        "normatives_sha256": _sha256(normatives),
    }
    payload["target_provenance_sha256"] = hashlib.sha256(
        canonical_bytes(payload)
    ).hexdigest()
    return payload


def main() -> int:
    args = _parser().parse_args()
    if args.batch_size < 1:
        raise ValueError("batch-size должен быть положительным")
    training = json.loads(args.split_report.read_text(encoding="utf-8"))
    selected_buckets = tuple(args.buckets)
    expected = _selected_identities(training, selected_buckets)
    model_schedule = args.model_dir / "Model_Z_sch.inc"
    provenance = _target_provenance(
        project_root=Path(__file__).resolve().parents[1],
        model_schedule=model_schedule,
        normatives=args.normatives,
    )
    payload = (
        json.loads(args.output.read_text(encoding="utf-8"))
        if args.output.exists()
        else {
            "format": "aios.surrogate-npv-labels.v1",
            "dataset_hash": training["dataset_hash"],
            "split_report": str(args.split_report),
            "split_report_sha256": _sha256(args.split_report),
            "included_buckets": list(selected_buckets),
            "historical_test_read": "test" in selected_buckets,
            "expected_rows": len(expected),
            "target_provenance": provenance,
            "rows": {},
        }
    )
    if payload.get("format") != "aios.surrogate-npv-labels.v1":
        raise RuntimeError(f"неизвестный labels format: {payload.get('format')}")
    if payload.get("dataset_hash") != training["dataset_hash"]:
        raise RuntimeError("labels относятся к другому dataset_hash")
    expected_metadata = {
        "split_report_sha256": _sha256(args.split_report),
        "included_buckets": list(selected_buckets),
        "historical_test_read": "test" in selected_buckets,
        "expected_rows": len(expected),
        "target_provenance": provenance,
    }
    for field, value in expected_metadata.items():
        if payload.get(field) != value:
            raise RuntimeError(f"labels provenance differs: {field}")
    _validate_label_rows(payload, expected)

    parsed = parse_schedule(model_schedule.read_bytes())
    normatives = load_normatives(args.normatives)
    policies = default_policies()
    material_contexts = _material_contexts(args.model_dir, args.data_root, expected)
    cache_records = _cache_index(args.data_root)
    caches = {
        source: RunCache(args.data_root / source / "cache")
        for source, _, _ in DATASETS
    }
    emitter = OpmDeckEmitter(args.model_dir)
    summary_plan = build_summary_plan(args.model_dir, emitter.source_wells)
    densities = load_density_by_pvtnum(args.model_dir)
    response_loader = ResponseLoader()
    pending = []
    for bucket, identity in expected:
        key = f"{identity['source_dataset']}:{identity['scenario_id']}"
        if key not in payload["rows"]:
            pending.append((key, bucket, identity))
    print(
        f"labels: готово {len(expected) - len(pending)}/{len(expected)}; "
        f"осталось {len(pending)}",
        flush=True,
    )

    started = time.monotonic()
    for start in range(0, len(pending), args.batch_size):
        batch = pending[start : start + args.batch_size]
        responses = _load_cached_responses(
            [identity for _, _, identity in batch],
            material_contexts=material_contexts,
            cache_records=cache_records,
            caches=caches,
            loader=response_loader,
            summary_plan=summary_plan,
            densities=densities,
        )
        for (key, bucket, identity), response in zip(batch, responses, strict=True):
            npv = analyze_base_case(
                response,
                parsed.dates,
                parsed.t0_deck_date_index,
                normatives,
                policies,
            ).npv_methodology
            if not math.isfinite(npv):
                raise RuntimeError(f"{key}: calculated NPV is non-finite")
            payload["rows"][key] = {
                "source_dataset": identity["source_dataset"],
                "scenario_id": identity["scenario_id"],
                "canonical_schedule_hash": identity["canonical_schedule_hash"],
                "response_hash": response.response_hash,
                "bucket": bucket,
                "npv_rub": npv,
            }
        _save(args.output, payload)
        print(
            f"готово {len(payload['rows'])}/{len(expected)}; "
            f"elapsed={time.monotonic() - started:.1f}s",
            flush=True,
        )
    _validate_label_rows(payload, expected)
    if len(payload["rows"]) != len(expected):
        raise RuntimeError(
            f"label population is incomplete: {len(payload['rows'])}/{len(expected)}"
        )
    if _sha256(args.split_report) != payload["split_report_sha256"]:
        raise RuntimeError("split report changed during label build")
    if (
        _target_provenance(
            project_root=Path(__file__).resolve().parents[1],
            model_schedule=model_schedule,
            normatives=args.normatives,
        )
        != provenance
    ):
        raise RuntimeError("target provenance changed during historical label build")
    print(f"готово: {args.output}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
