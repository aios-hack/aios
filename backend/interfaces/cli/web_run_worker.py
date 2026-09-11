from __future__ import annotations
import argparse
import json
import os
from pathlib import Path

from backend.contexts.simulation.infrastructure.preflight import (
    DockerPreflightError,
    ensure_docker_ready,
)
from backend.interfaces.cli.runner import run as run_cli


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument('mode', choices=['search', 'verify'])
    parser.add_argument('--directory', type=Path, required=True)
    parser.add_argument('--budget', type=int, default=30)
    args = parser.parse_args()
    root = args.directory.resolve()
    os.environ['AIOS_CONSTRAINTS_PATH'] = str(root / 'constraints.json')
    os.environ['AIOS_SEARCH_DIAGNOSTICS_PATH'] = str(root / 'diagnostics.json')
    import torch
    torch.set_num_threads(2)
    from backend.contexts.runs.application.workflow import RunRequest, RunWorkflow
    workflow = RunWorkflow(root.parent)
    if args.mode == 'search':
        from backend.contexts.optimization.application.search_use_case import run_search
        from backend.interfaces.cli.run import build_provenance, resolve_constraints
        outcome = run_search(budget=args.budget)
        constraints = resolve_constraints(root / 'constraints.json')
        manifest = workflow.search(
            RunRequest(
                root.name,
                outcome.schedule,
                outcome.predicted_npv,
                provenance=build_provenance(outcome, constraints),
                constraints=constraints,
            )
        )
        (root / 'provenance.json').write_text(json.dumps(outcome.provenance, ensure_ascii=False, indent=2))
    else:
        try:
            ensure_docker_ready()
        except DockerPreflightError as error:
            raise SystemExit(error.report.message) from error
        from backend.interfaces.cli.run import load_run_request
        from backend.contexts.optimization.application.verification_run import (
            verify_schedule,
            persist_observation,
        )
        request = load_run_request(root.parent, root.name)

        def verify_and_record(schedule, work_root):
            result = verify_schedule(schedule, work_root)
            persist_observation(schedule, result, predicted_npv=request.predicted_npv,
                                observation_root=root / 'observation',
                                metadata={'constraints_path': str(root / 'constraints.json')})
            return result
        manifest = workflow.verify(request, verify_and_record)
    print(json.dumps(manifest.as_dict(), ensure_ascii=False), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(run_cli(main))
