from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

import torch

import backend.contexts.surrogate.application.model as model
from backend.interfaces.cli.surrogate.tools import surrogate_train_tensors as trainer
from backend.shared.json_io import read_json


class IndependentControl(model._ScenarioBatches):
    def __iter__(self):
        order = torch.randperm(len(self.offsets), generator=self.generator)
        for position in range(0, len(order), self.scenarios_per_batch):
            chosen = order[position:position + self.scenarios_per_batch]
            if len(chosen) < 2:
                continue
            rows, groups = [], []
            for group, index in enumerate(chosen.tolist()):
                start, size = self.offsets[index]
                take = min(self.nodes_per_scenario, size)
                rows.append(torch.randperm(size, generator=self.generator)[:take] + start)
                groups.append(torch.full((take,), group, dtype=torch.long))
            selected = torch.cat(rows)
            yield (
                *(tensor[selected] for tensor in self.tensors), torch.cat(groups), len(chosen),
                *((self.scenario_targets[chosen],) if self.scenario_targets is not None else ()),
            )


def main():
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--sampling", choices=("independent", "shared"), required=True)
    experiment, remainder = parser.parse_known_args()
    settings = trainer._parser().parse_args(remainder)
    sources = {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in (
        Path(__file__), Path(trainer.__file__), Path(model.__file__),
    )}
    original = model._ScenarioBatches
    try:
        if experiment.sampling == "independent":
            model._ScenarioBatches = IndependentControl
        sys.argv = [sys.argv[0], *remainder]
        trainer.main()
    finally:
        model._ScenarioBatches = original
    report = settings.output_dir / "training_report.json"
    payload = read_json(report)
    payload["experiment"] = {"sampling": experiment.sampling, "source_sha256": sources,
                             "promotion": False, "test_used_for_selection": False}
    payload["ranking_sampling"] = experiment.sampling
    report.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")


if __name__ == "__main__":
    main()
