from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pytest

from contracts import N_INTERVALS
from surrogate.ensemble import TrajectoryEnsemble
from surrogate.features import SurrogateInput
from surrogate.ood import OodScore, ScoredPrediction
from surrogate.raw_model_output import RawModelOutput, RawWellStepPrediction
from tools.surrogate_select_physical_ensemble import _weight_candidates


@dataclass
class _FakeModel:
    version: str
    value: float
    dataset_hash: str = "dataset"
    wells: tuple[str, ...] = ("P1",)
    static_feature_names: tuple[str, ...] = ()
    domain: str = "same-domain"

    def predict(self, candidate: SurrogateInput) -> ScoredPrediction:
        nodes = tuple(
            RawWellStepPrediction(
                well="P1",
                control_step=step,
                oil_mass_delta=self.value,
                liquid_volume_delta=self.value * 2.0,
                injection_volume_delta=0.0,
                liquid_rate=self.value,
                injection_rate=0.0,
                bhp=100.0 + self.value,
            )
            for step in range(N_INTERVALS)
        )
        return ScoredPrediction(
            output=RawModelOutput(
                canonical_schedule_hash=candidate.canonical_schedule_hash,
                wells=("P1",),
                nodes=nodes,
            ),
            ood=OodScore(score=0.0, exceedances=(), n_nodes=N_INTERVALS),
        )


def test_ensemble_averages_physical_channels_and_preserves_ood() -> None:
    models = (_FakeModel("m1", 2.0), _FakeModel("m2", 6.0))
    ensemble = TrajectoryEnsemble(
        models=models,  # type: ignore[arg-type]
        weights=(0.25, 0.75),
        member_paths=(Path("m1.pt"), Path("m2.pt")),
    )
    candidate = SurrogateInput(
        canonical_schedule_hash="schedule",
        wells=("P1",),
        static_feature_names=(),
        nodes=(),
        lambda_edges=(),
    )

    prediction = ensemble.predict(candidate)

    assert prediction.ood.score == 0.0
    assert prediction.output.nodes[0].oil_mass_delta == pytest.approx(5.0)
    assert prediction.output.nodes[0].liquid_volume_delta == pytest.approx(10.0)
    assert prediction.output.nodes[0].bhp == pytest.approx(105.0)
    assert ensemble.version == ensemble._fingerprint()


def test_validation_weight_grid_covers_singles_pairs_and_diverse_triples() -> None:
    candidates = list(_weight_candidates(3))

    assert len(candidates) == 16
    assert ((0,), (1.0,)) in candidates
    assert ((0, 1), (0.25, 0.75)) in candidates
    assert ((0, 1, 2), (0.5, 0.25, 0.25)) in candidates
    assert all(sum(weights) == pytest.approx(1.0) for _, weights in candidates)
