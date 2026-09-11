from __future__ import annotations

import argparse
import json
import math
import re
import sys
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any, Iterable, Sequence

from backend.shared.paths import out_root, project_root

FORMAT = "aios.ood-calibration.v1"
DEFAULT_ARTIFACT = "out/ood-calibration.json"
CONSERVATIVE_THRESHOLD = 0.0
MIN_POINTS_FOR_CURVE = 3
_OOD_IN_MESSAGE = re.compile(r"ood_score=([-+0-9.eE]+)")


class OodCalibrationError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class CalibrationPoint:
    run_id: str
    schedule_hash: str
    ood_score: float
    npv_predicted: float
    npv_verified: float
    relative_error: float
    source: str


@dataclass(frozen=True, slots=True)
class CalibrationResult:
    threshold: float
    threshold_origin: str
    tolerated_relative_error: float
    point_count: int
    rejected_reference_count: int
    curve_is_reliable: bool
    rationale: str
    points: tuple[CalibrationPoint, ...]
    rejected_scores: tuple[float, ...]

    def as_payload(self) -> dict[str, Any]:
        return {
            "format": FORMAT,
            "threshold": self.threshold,
            "threshold_origin": self.threshold_origin,
            "tolerated_relative_error": self.tolerated_relative_error,
            "point_count": self.point_count,
            "rejected_reference_count": self.rejected_reference_count,
            "curve_is_reliable": self.curve_is_reliable,
            "rationale": self.rationale,
            "points": [asdict(point) for point in self.points],
            "rejected_scores": list(self.rejected_scores),
        }


def _read_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise OodCalibrationError(f"{path} cannot be read: {error}") from error
    if not isinstance(payload, dict):
        raise OodCalibrationError(f"{path}: a JSON object was expected")
    return payload


def _finite_float(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    number = float(value)
    return number if math.isfinite(number) else None


def _ood_from_violation(entry: dict[str, Any]) -> float | None:
    direct = _finite_float(entry.get("ood_score"))
    if direct is not None:
        return direct
    for item in entry.get("violations") or ():
        if not isinstance(item, dict):
            continue
        match = _OOD_IN_MESSAGE.search(str(item.get("what", "")))
        if match is not None:
            parsed = _finite_float(float(match.group(1)))
            if parsed is not None:
                return parsed
    return None


def _accepted_candidate_score(entry: dict[str, Any], threshold_used: float) -> float | None:
    explicit = _finite_float(entry.get("ood_score"))
    if explicit is not None:
        return explicit
    if entry.get("feasible") is True:
        return threshold_used
    return None


def _selected_prediction(diagnostics: dict[str, Any], predicted: float) -> dict[str, Any] | None:
    evaluations = diagnostics.get("evaluations")
    if not isinstance(evaluations, list):
        return None
    best: dict[str, Any] | None = None
    best_value = -math.inf
    for entry in evaluations:
        if not isinstance(entry, dict) or entry.get("feasible") is not True:
            continue
        value = _finite_float(entry.get("npv_predicted"))
        if value is None:
            continue
        if math.isclose(value, predicted, rel_tol=1e-12, abs_tol=1e-6):
            return entry
        if value > best_value:
            best_value = value
            best = entry
    return best


def _rejected_scores(diagnostics: dict[str, Any]) -> tuple[float, ...]:
    evaluations = diagnostics.get("evaluations")
    if not isinstance(evaluations, list):
        return ()
    scores: list[float] = []
    for entry in evaluations:
        if not isinstance(entry, dict) or entry.get("feasible") is True:
            continue
        score = _ood_from_violation(entry)
        if score is not None:
            scores.append(score)
    return tuple(scores)


def collect_run_point(run_dir: Path) -> tuple[CalibrationPoint | None, tuple[float, ...]]:
    manifest_path = run_dir / "manifest.json"
    diagnostics_path = run_dir / "diagnostics.json"
    if not diagnostics_path.is_file():
        return None, ()
    diagnostics = _read_json(diagnostics_path)
    rejected = _rejected_scores(diagnostics)
    if not manifest_path.is_file():
        return None, rejected
    manifest = _read_json(manifest_path)
    predicted = _finite_float(manifest.get("predicted_npv"))
    verified = _finite_float(manifest.get("verified_npv"))
    if predicted is None or verified is None or verified == 0.0:
        return None, rejected
    threshold_used = _finite_float(diagnostics.get("ood_threshold"))
    if threshold_used is None:
        threshold_used = CONSERVATIVE_THRESHOLD
    entry = _selected_prediction(diagnostics, predicted)
    if entry is None:
        return None, rejected
    score = _accepted_candidate_score(entry, threshold_used)
    if score is None:
        return None, rejected
    point = CalibrationPoint(
        run_id=str(manifest.get("run_id", run_dir.name)),
        schedule_hash=str(manifest.get("schedule_hash", "")),
        ood_score=score,
        npv_predicted=predicted,
        npv_verified=verified,
        relative_error=abs(predicted - verified) / abs(verified),
        source=str(diagnostics_path),
    )
    return point, rejected


def collect_points(run_roots: Sequence[Path]) -> tuple[list[CalibrationPoint], list[float]]:
    points: list[CalibrationPoint] = []
    rejected: list[float] = []
    for root in run_roots:
        if not root.is_dir():
            continue
        for run_dir in sorted(path for path in root.iterdir() if path.is_dir()):
            point, scores = collect_run_point(run_dir)
            rejected.extend(scores)
            if point is not None:
                points.append(point)
    points.sort(key=lambda item: (item.ood_score, item.run_id))
    return points, sorted(rejected)


def choose_threshold(
    points: Sequence[CalibrationPoint],
    rejected: Sequence[float],
    tolerated_relative_error: float,
) -> CalibrationResult:
    if not points:
        raise OodCalibrationError(
            "calibration is impossible: there is not a single forecast-versus-fact pair; "
            "at least one run with a manifest.json holding both "
            "predicted_npv and verified_npv is required, plus a diagnostics.json with evaluated candidates"
        )
    if tolerated_relative_error <= 0.0 or not math.isfinite(tolerated_relative_error):
        raise OodCalibrationError(
            f"the tolerated relative error {tolerated_relative_error} "
            "must be a positive finite number"
        )
    within = [point for point in points if point.relative_error <= tolerated_relative_error]
    reliable = len(points) >= MIN_POINTS_FOR_CURVE
    if not within:
        best = min(points, key=lambda item: item.relative_error)
        raise OodCalibrationError(
            "calibration is impossible: none of the "
            f"{len(points)} measured points fits into the tolerated "
            f"error {tolerated_relative_error:.6g}; the smallest measured "
            f"error is {best.relative_error:.6g} on run {best.run_id}"
        )
    threshold = max(point.ood_score for point in within)
    origin = "measured-error-curve" if reliable else "measured-error-curve/insufficient-points"
    worst = max(point.relative_error for point in within)
    rationale = (
        f"tau={threshold:.6g} is the largest ood_score among {len(within)} of "
        f"{len(points)} measured points whose relative NPV forecast error "
        f"did not exceed {tolerated_relative_error:.6g} (the worst inside the threshold "
        f"is {worst:.6g}). Rejected candidates with a known ood_score: "
        f"{len(rejected)}"
    )
    if not reliable:
        rationale += (
            f". Points {len(points)} < {MIN_POINTS_FOR_CURVE}: the error-versus-OOD curve "
            "is unreliable on so few points, so tau is a lower bound rather than a measured "
            "inflection point"
        )
    return CalibrationResult(
        threshold=threshold,
        threshold_origin=origin,
        tolerated_relative_error=tolerated_relative_error,
        point_count=len(points),
        rejected_reference_count=len(rejected),
        curve_is_reliable=reliable,
        rationale=rationale,
        points=tuple(points),
        rejected_scores=tuple(rejected),
    )


def calibrate(
    run_roots: Sequence[Path],
    tolerated_relative_error: float,
) -> CalibrationResult:
    points, rejected = collect_points(run_roots)
    return choose_threshold(points, rejected, tolerated_relative_error)


def write_artifact(result: CalibrationResult, path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(result.as_payload(), ensure_ascii=False, indent=2, allow_nan=False),
        encoding="utf-8",
    )
    return path


def load_calibration(path: Path) -> CalibrationResult:
    payload = _read_json(path)
    if payload.get("format") != FORMAT:
        raise OodCalibrationError(f"{path}: unsupported OOD calibration format")
    threshold = _finite_float(payload.get("threshold"))
    if threshold is None or threshold < 0.0:
        raise OodCalibrationError(f"{path}: the calibration threshold is not finite or is negative")
    count = payload.get("point_count")
    if not isinstance(count, int) or count < 1:
        raise OodCalibrationError(f"{path}: a calibration without a single measured point")
    points = payload.get("points")
    if not isinstance(points, list) or len(points) != count:
        raise OodCalibrationError(
            f"{path}: {count} points are declared but "
            f"{len(points) if isinstance(points, list) else 'not a list'} are recorded"
        )
    tolerated = _finite_float(payload.get("tolerated_relative_error"))
    if tolerated is None or tolerated <= 0.0:
        raise OodCalibrationError(f"{path}: the tolerated error is not set")
    return CalibrationResult(
        threshold=threshold,
        threshold_origin=str(payload.get("threshold_origin", "unknown")),
        tolerated_relative_error=tolerated,
        point_count=count,
        rejected_reference_count=int(payload.get("rejected_reference_count", 0)),
        curve_is_reliable=bool(payload.get("curve_is_reliable", False)),
        rationale=str(payload.get("rationale", "")),
        points=tuple(
            CalibrationPoint(
                run_id=str(item.get("run_id", "")),
                schedule_hash=str(item.get("schedule_hash", "")),
                ood_score=float(item["ood_score"]),
                npv_predicted=float(item["npv_predicted"]),
                npv_verified=float(item["npv_verified"]),
                relative_error=float(item["relative_error"]),
                source=str(item.get("source", "")),
            )
            for item in points
        ),
        rejected_scores=tuple(float(value) for value in payload.get("rejected_scores", ())),
    )


def _default_run_roots() -> list[Path]:
    return [out_root() / "web-runs"]


def _parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="ood_calibration")
    parser.add_argument("--runs", type=Path, action="append", default=None)
    parser.add_argument("--tolerated-relative-error", type=float, default=0.01)
    parser.add_argument("--out", type=Path, default=project_root() / DEFAULT_ARTIFACT)
    return parser.parse_args(argv)


def _report(result: CalibrationResult, destination: Path, stream: Any) -> None:
    print(f"points: {result.point_count}", file=stream)
    for point in result.points:
        print(
            f"  {point.run_id}: ood_score={point.ood_score:.6g}, "
            f"relative NPV error={point.relative_error:.6g}",
            file=stream,
        )
    print(f"τ = {result.threshold:.6g} ({result.threshold_origin})", file=stream)
    print(result.rationale, file=stream)
    print(f"artifact: {destination}", file=stream)


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(argv)
    roots: Iterable[Path] = args.runs if args.runs else _default_run_roots()
    try:
        result = calibrate(list(roots), args.tolerated_relative_error)
    except OodCalibrationError as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    destination = write_artifact(result, args.out)
    _report(result, destination, sys.stdout)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
