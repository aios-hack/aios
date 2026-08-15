from pathlib import Path

import pytest

from ui.deck import load_completions, load_wellheads

DECK_PATH: Path = Path(__file__).resolve().parents[3] / "docs" / "models" / "Model_Z" / "Model_Z_sch.inc"
NI: int = 91
NJ: int = 102
NK: int = 59
EXPECTED_WELLS: int = 103
MIN_UNIQUE_POINTS: int = 95


@pytest.fixture(scope="module")
def wellheads() -> dict[str, tuple[int, int]]:
    return load_wellheads(DECK_PATH)


@pytest.fixture(scope="module")
def completions() -> dict[str, list[tuple[int, int, int, int]]]:
    return load_completions(DECK_PATH)


def test_wells_count_and_string_ids(wellheads: dict[str, tuple[int, int]]) -> None:
    assert len(wellheads) == EXPECTED_WELLS
    assert all(isinstance(well, str) and well for well in wellheads)
    assert len(set(wellheads)) == EXPECTED_WELLS


def test_heads_inside_grid(wellheads: dict[str, tuple[int, int]]) -> None:
    for well, (i, j) in wellheads.items():
        assert 1 <= i <= NI, well
        assert 1 <= j <= NJ, well


def test_heads_spread_not_clumped(wellheads: dict[str, tuple[int, int]]) -> None:
    xs = [i for i, _ in wellheads.values()]
    ys = [j for _, j in wellheads.values()]
    width = max(xs) - min(xs) + 1
    height = max(ys) - min(ys) + 1
    assert width >= NI / 2
    assert height >= NJ / 2
    assert len(set(wellheads.values())) >= MIN_UNIQUE_POINTS


def test_completions_intervals_for_every_well(
    wellheads: dict[str, tuple[int, int]],
    completions: dict[str, list[tuple[int, int, int, int]]],
) -> None:
    assert set(completions) == set(wellheads)
    for well, intervals in completions.items():
        assert intervals, well
        for i, j, k1, k2 in intervals:
            assert 1 <= i <= NI, well
            assert 1 <= j <= NJ, well
            assert 1 <= k1 <= k2 <= NK, well
