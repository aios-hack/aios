import pytest
import torch

from backend.presentation.cli.surrogate_adapt import ensure_disjoint_splits, sample_scenarios, main


@pytest.mark.parametrize("splits", [(["a"], ["a"], ["c"]),
                                    (["a"], ["b"], ["a"]),
                                    (["a"], ["b"], ["b"])])
def test_rejects_scenario_leakage(splits):
    with pytest.raises(ValueError, match="leakage"):
        ensure_disjoint_splits(*splits)


def test_repeated_training_examples_do_not_create_cross_split_leakage():
    ensure_disjoint_splits(["a", "a"], ["b"], ["c"])


def test_replay_sampling_preserves_whole_scenarios_and_feature_prefix():
    x = torch.arange(24).reshape(6, 4)
    wells = torch.arange(6)
    y = torch.arange(12).reshape(6, 2)
    sampled = sample_scenarios((x, wells, y), [2, 1, 3], [2, 0], 2)
    rows = [3, 4, 5, 0, 1]
    assert torch.equal(sampled[0], x[rows, :2])
    assert torch.equal(sampled[1], wells[rows])
    assert torch.equal(sampled[2], y[rows])


@pytest.mark.parametrize("extra", [["--learning-rates", "nan"],
                                   ["--learning-rates", "0"],
                                   ["--learning-rates", "0.001", "0.001"],
                                   ["--members", "2", "2"],
                                   ["--validation-scenarios", "0"],
                                   ["--local-train", "same", "--local-validation", "same"]])
def test_invalid_experiment_budgets_rejected_before_loading_data(tmp_path, extra):
    destination = tmp_path / "experiment"
    with pytest.raises(SystemExit) as caught:
        main(["--tensors", "missing", "--runs-root", "missing", "--out", str(destination), *extra])
    assert caught.value.code == 2
    assert not destination.exists()
