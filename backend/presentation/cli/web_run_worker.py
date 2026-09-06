"""Isolated process for a browser-requested search or exact-plan verification."""
from __future__ import annotations
import argparse
import json
import os
import subprocess
from pathlib import Path


def main():
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
    from backend.application.runs import RunRequest, RunWorkflow
    workflow = RunWorkflow(root.parent)
    if args.mode == 'search':
        from backend.application.optimization.search_run import run_search
        outcome = run_search(budget=args.budget)
        manifest = workflow.search(RunRequest(root.name, outcome.schedule, outcome.predicted_npv))
        (root / 'provenance.json').write_text(json.dumps(outcome.provenance, ensure_ascii=False, indent=2))
    else:
        # Fail promptly when Docker is unavailable, before preparing an expensive deck.
        subprocess.run(['docker', 'info', '--format', '{{.ServerVersion}}'], check=True, timeout=15)
        from backend.presentation.cli.run import load_run_request
        from backend.application.optimization.verification_run import verify_schedule, persist_observation
        request = load_run_request(root.parent, root.name)
        def verify_and_record(schedule, work_root):
            result = verify_schedule(schedule, work_root)
            persist_observation(schedule, result, predicted_npv=request.predicted_npv,
                                observation_root=root / 'observation',
                                metadata={'constraints_path': str(root / 'constraints.json')})
            return result
        manifest = workflow.verify(request, verify_and_record)
    print(json.dumps(manifest.as_dict(), ensure_ascii=False), flush=True)


if __name__ == '__main__':
    main()
