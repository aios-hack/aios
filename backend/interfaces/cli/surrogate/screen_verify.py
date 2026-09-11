"""Buy one OPM label for a previously frozen screening experiment."""
import argparse
import hashlib
import json
import os
import time
from pathlib import Path

from backend.contexts.optimization.application.verification_run import verify_schedule
from backend.application.runs import RunWorkflow
from backend.core.contracts import hash_schedule
from backend.contexts.runs.infrastructure.provenance import OPM_IMAGE_ENV
from backend.contexts.connectivity.infrastructure.groups_artifact import load as load_groups
from backend.domain.economics import save_response_artifact
from backend.interfaces.cli.run import load_run_request, require_docker
from backend.interfaces.cli.runner import run as run_cli
from backend.shared.json_io import read_json


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--experiment", type=Path, required=True)
    parser.add_argument("--runs-root", type=Path, required=True)
    parser.add_argument("--arm", choices=("model-top", "unranked-control",
                                          "trajectory-top", "hybrid-top",
                                          "direct-head-control"), required=True)
    args = parser.parse_args(argv)
    report_path = args.experiment / "results" / f"{args.arm}.json"
    if report_path.exists():
        parser.error("arm result already exists; refusing to overwrite the benchmark")
    frozen = args.experiment / "screening.json"
    digest = hashlib.sha256(frozen.read_bytes()).hexdigest()
    payload = read_json(frozen)
    row = next(r for r in payload["selection"] if r["arm"] == args.arm)
    request = load_run_request(args.runs_root, row["run_id"])
    if hash_schedule(request.schedule) != row["schedule_hash"]:
        parser.error("schedule differs from frozen selection")
    expected_image = request.provenance.opm_image or ""
    if "@sha256:" not in expected_image:
        parser.error("verification requires a pinned OPM image; unresolved historical results cannot be relabeled")
    os.environ[OPM_IMAGE_ENV] = expected_image
    directory = args.runs_root / request.run_id
    grouping = load_groups(directory / "inputs/groups.json")
    require_docker()
    had_cache = any((directory / "opm/cache").glob("*.json"))
    started = time.perf_counter()
    def measure(schedule, work_root):
        result = verify_schedule(schedule, work_root, run_dir=directory,
                                 constraints=request.constraints, groups=grouping.groups)
        if result.response is not None:
            save_response_artifact(result.response, directory / "response.json")
        return result
    manifest = RunWorkflow(args.runs_root).verify(request, measure)
    elapsed = time.perf_counter() - started
    if hashlib.sha256(frozen.read_bytes()).hexdigest() != digest:
        raise RuntimeError("experiment changed during OPM verification")
    economics = read_json(directory / 'economics/result.json')
    result = dict(arm=args.arm, run_id=request.run_id, schedule_hash=row["schedule_hash"],
                  screening_sha256=digest, sound=manifest.sound,
                  verified_npv=manifest.verified_npv, measured_npv=economics["measured_npv"],
                  opm_source_run_id=economics["source_run_id"],
                  verification_seconds=elapsed, started_with_cache=had_cache,
                  anchor_verified_npv=payload["anchor"]["verified_npv_rub"])
    (args.experiment / "results").mkdir(exist_ok=True)
    report_path.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result, indent=2), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(run_cli(main))
