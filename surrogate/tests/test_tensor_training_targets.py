"""Synthetic identities only: label alignment and split/provenance contracts."""
import hashlib
from copy import deepcopy

import pytest
import torch

from contracts import canonical_bytes
from surrogate.npv_target import TARGET_PROVENANCE_FORMAT, TARGET_SOURCE_FILES
from tools.surrogate_train_tensors import _exact_targets


def _inputs():
    provenance = {
        "format": TARGET_PROVENANCE_FORMAT, "target": "npv_methodology_rub",
        "source_sha256": {name: "a" * 64 for name in TARGET_SOURCE_FILES},
        "methodology_version_hash": "a" * 64, "model_schedule_sha256": "a" * 64,
        "normatives_sha256": "a" * 64,
    }
    provenance["target_provenance_sha256"] = hashlib.sha256(canonical_bytes(provenance)).hexdigest()
    identities = [{"source_dataset": "synthetic-shape-test", "scenario_id": str(i),
                   "canonical_schedule_hash": str(i) * 64} for i in range(3)]
    blob = {"dataset_hash": "d" * 64, "identities": {
        "train": [identities[1], identities[0]], "validation": [identities[2]],
    }}
    labels = {"format": "aios.surrogate-npv-labels.v1", "dataset_hash": "d" * 64,
              "target_provenance": provenance, "rows": {
                  str(i): {**row, "bucket": "validation" if i == 2 else "train", "npv_rub": i + 10.}
                  for i, row in enumerate(identities)
              }}
    return blob, labels


def test_exact_npv_labels_follow_tensor_identity_order():
    blob, labels = _inputs()
    targets = _exact_targets(blob, labels)
    assert targets["train"].dtype is torch.float64
    assert targets["train"].tolist() == [11., 10.]
    assert targets["validation"].tolist() == [12.]


@pytest.mark.parametrize("error", ["missing", "bucket", "hash", "nonfinite", "provenance", "overlap"])
def test_invalid_or_leaking_exact_targets_are_rejected(error):
    blob, labels = deepcopy(_inputs())
    if error == "missing":
        del labels["rows"]["0"]
    elif error == "bucket":
        labels["rows"]["0"]["bucket"] = "test"
    elif error == "hash":
        labels["dataset_hash"] = "e" * 64
    elif error == "nonfinite":
        labels["rows"]["0"]["npv_rub"] = float("nan")
    elif error == "provenance":
        labels["target_provenance"]["normatives_sha256"] = "b" * 64
    else:
        blob["identities"]["validation"] = blob["identities"]["train"][:1]
    with pytest.raises(RuntimeError):
        _exact_targets(blob, labels)
