from __future__ import annotations

import pytest

from aios_backend.core.contracts import N_INTERVALS
from aios_backend.ml.surrogate import RawModelOutput, RawWellStepPrediction


def _node(well: str = "P", control_step: int = 0, **overrides) -> RawWellStepPrediction:
    values = dict(
        well=well,
        control_step=control_step,
        oil_mass_delta=1.0,
        liquid_volume_delta=2.0,
        injection_volume_delta=0.0,
        liquid_rate=10.0,
        injection_rate=0.0,
        bhp=45.0,
    )
    values.update(overrides)
    return RawWellStepPrediction(**values)


def _full_output(wells: tuple[str, ...] = ("I", "P")) -> RawModelOutput:
    nodes = tuple(
        _node(well=well, control_step=step)
        for well in wells
        for step in range(N_INTERVALS)
    )
    return RawModelOutput(canonical_schedule_hash="hash", wells=wells, nodes=nodes)


def test_valid_construction_round_trips_fields() -> None:
    output = _full_output()
    assert output.wells == ("I", "P")
    assert len(output.nodes) == 2 * N_INTERVALS


def test_rejects_control_step_out_of_range() -> None:
    with pytest.raises(ValueError, match="control_step"):
        _node(control_step=N_INTERVALS)


def test_rejects_non_finite_numeric_field() -> None:
    with pytest.raises(ValueError, match="liquid_rate"):
        _node(liquid_rate=float("nan"))


def test_rejects_negative_numeric_field() -> None:
    with pytest.raises(ValueError, match="bhp"):
        _node(bhp=-1.0)


def test_rejects_missing_pair() -> None:
    wells = ("P",)
    nodes = tuple(_node(well="P", control_step=step) for step in range(N_INTERVALS - 1))
    with pytest.raises(ValueError, match="не покрывает"):
        RawModelOutput(canonical_schedule_hash="hash", wells=wells, nodes=nodes)


def test_rejects_duplicate_pair() -> None:
    wells = ("P",)
    nodes = tuple(
        _node(well="P", control_step=step) for step in range(N_INTERVALS)
    ) + (_node(well="P", control_step=0),)
    with pytest.raises(ValueError, match="дублирующиеся"):
        RawModelOutput(canonical_schedule_hash="hash", wells=wells, nodes=nodes)


def test_rejects_node_on_unknown_well() -> None:
    wells = ("P",)
    nodes = tuple(
        _node(well="P", control_step=step) for step in range(N_INTERVALS)
    )
    nodes = nodes[:-1] + (_node(well="FOREIGN", control_step=N_INTERVALS - 1),)
    with pytest.raises(ValueError, match="не покрывает"):
        RawModelOutput(canonical_schedule_hash="hash", wells=wells, nodes=nodes)


def test_rejects_duplicate_well_in_axis() -> None:
    with pytest.raises(ValueError, match="дубликаты"):
        _full_output(wells=("P", "P"))
