import json

import pytest

from backend.contexts.optimization.infrastructure.champion import CONDITION_KEYS, promote_champion


def candidate(npv):
    return dict({key: "same" for key in CONDITION_KEYS}, sound=True,
                verified_npv_rub=npv, run_id="run", schedule_hash="hash")


def test_regressions_and_rejections_never_replace_verified_incumbent(tmp_path):
    path = tmp_path / "champion.json"
    assert promote_champion(path, candidate(100))
    for entry in (candidate(99), candidate(100), {**candidate(1000), "sound": False}):
        assert not promote_champion(path, entry)
        assert json.loads(path.read_text())["verified_npv_rub"] == 100
    assert promote_champion(path, candidate(101))
    assert json.loads(path.read_text())["verified_npv_rub"] == 101


@pytest.mark.parametrize("key", CONDITION_KEYS)
def test_incomparable_economics_never_replace_champion(tmp_path, key):
    path = tmp_path / "champion.json"
    promote_champion(path, candidate(100))
    with pytest.raises(ValueError, match="different conditions"):
        promote_champion(path, {**candidate(200), key: "different"})
    assert json.loads(path.read_text())["verified_npv_rub"] == 100


@pytest.mark.parametrize("value", [None, True, float("nan"), float("inf")])
def test_unmeasured_or_invalid_npv_is_refused(tmp_path, value):
    with pytest.raises(ValueError):
        promote_champion(tmp_path / "champion.json", candidate(value))
