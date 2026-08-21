from __future__ import annotations

import math

from dataclasses import replace
from datetime import date, timedelta

import pytest

torch = pytest.importorskip("torch")

from aios_backend.core.contracts import (  # noqa: E402
    ActiveControlMode,
    Availability,
    IntervalResponse,
    N_INTERVALS,
    OperatingStatus,
    ResponseArtifact,
    Role,
    StateAtDate,
)
from aios_backend.ml.surrogate.features import SurrogateInput, WellStepFeatures  # noqa: E402
from aios_backend.ml.surrogate.model import (
    Standardizer,
    _money_weights,
    _targets,
    _watercut_row,
    _scenario_money,
    _spearman,  # noqa: E402
    ModelConfig,
    SurrogateModelError,
    TrainingExample,
    TrajectorySurrogate,
    _targets,
    split_examples,
)
from aios_backend.ml.surrogate.ood import ScoredPrediction  # noqa: E402


WELLS = ("I", "P")


def _input(schedule_hash: str = "schedule") -> SurrogateInput:
    start = date(2007, 1, 1)
    nodes = []
    for step in range(N_INTERVALS):
        for well in WELLS:
            injector = well == "I"
            nodes.append(
                WellStepFeatures(
                    control_step=step,
                    interval_start=start + timedelta(days=30 * step),
                    interval_end=start + timedelta(days=30 * (step + 1)),
                    well=well,
                    availability=Availability.AVAILABLE,
                    role=Role.INJ if injector else Role.PROD,
                    operating_status=OperatingStatus.OPEN,
                    setpoint_m3_per_day=20.0 if injector else 10.0,
                    effective_target_rate_m3_per_day=20.0 if injector else 10.0,
                    cumulative_target_liquid_m3=0.0 if injector else 300.0 * (step + 1),
                    cumulative_target_injection_m3=600.0 * (step + 1) if injector else 0.0,
                    cumulative_neighbor_injection_m3=60.0 * (step + 1) if not injector else 0.0,
                    current_neighbor_injection_m3_per_day=2.0 if not injector else 0.0,
                    event_count=1,
                    fixed_event_count=0,
                    static_values=(1.0 if injector else 2.0,),
                    lambda_window_start=start,
                    lambda_window_end=start + timedelta(days=30 * N_INTERVALS),
                )
            )
    return SurrogateInput(
        canonical_schedule_hash=schedule_hash,
        wells=WELLS,
        static_feature_names=("well_index",),
        nodes=tuple(nodes),
        lambda_edges=(),
    )


def _response() -> ResponseArtifact:
    intervals = []
    states = []
    for step in range(N_INTERVALS):
        for well in WELLS:
            injector = well == "I"
            intervals.append(
                IntervalResponse(
                    control_step=step,
                    well=well,
                    oil_mass_delta=0.0 if injector else 50.0 + step,
                    liquid_volume_delta=0.0 if injector else 200.0 + step,
                    injection_volume_delta=400.0 + step if injector else 0.0,
                )
            )
            states.append(
                StateAtDate(
                    deck_date_index=147 + step,
                    well=well,
                    liquid_rate=0.0 if injector else 7.0,
                    oil_rate=0.0 if injector else 2.0,
                    injection_rate=14.0 if injector else 0.0,
                    thp=10.0,
                    bhp=250.0 if injector else 75.0,
                    well_efficiency=1.0,
                    active_control_mode=ActiveControlMode.RATE_TARGET,
                )
            )
    return ResponseArtifact(
        source_run_id="real-opm-run",
        response_hash="response",
        state_at_date=tuple(states),
        interval_response=tuple(intervals),
    )


def _example(schedule_hash: str = "schedule") -> TrainingExample:
    return TrainingExample(_input(schedule_hash), _response())


def _model() -> TrajectorySurrogate:
    return TrajectorySurrogate.initialize(
        (_example(),),
        config=ModelConfig(
            hidden_width=12,
            hidden_layers=1,
            well_embedding_dim=4,
            batch_size=256,
            max_epochs=1,
            patience=1,
        ),
        dataset_hash="real-dataset-hash",
    )


def test_prediction_covers_contract_axes_and_always_carries_ood() -> None:
    prediction = _model().predict(_input())

    assert isinstance(prediction, ScoredPrediction)
    assert prediction.ood.score == 0.0
    assert prediction.output.wells == WELLS
    assert len(prediction.output.nodes) == len(WELLS) * N_INTERVALS
    assert all(
        value >= 0.0
        for node in prediction.output.nodes
        for value in (
            node.oil_mass_delta,
            node.liquid_volume_delta,
            node.injection_volume_delta,
            node.liquid_rate,
            node.injection_rate,
            node.bhp,
        )
    )


def test_role_masks_make_impossible_cross_role_flows_zero() -> None:
    nodes = _model().predict(_input()).output.nodes
    injector = next(node for node in nodes if node.well == "I")
    producer = next(node for node in nodes if node.well == "P")

    assert injector.oil_mass_delta == 0.0
    assert injector.liquid_volume_delta == 0.0
    assert injector.liquid_rate == 0.0
    assert producer.injection_volume_delta == 0.0
    assert producer.injection_rate == 0.0


def test_checkpoint_round_trip_keeps_version_and_prediction(tmp_path) -> None:
    model = _model()
    before = model.predict(_input()).output.nodes[0]

    loaded = TrajectorySurrogate.load(model.save(tmp_path / "surrogate.pt"))
    after = loaded.predict(_input()).output.nodes[0]

    assert loaded.version == model.version
    assert loaded.dataset_hash == "real-dataset-hash"
    assert after == before


def test_targets_clamp_only_tiny_negative_cumulative_roundoff() -> None:
    response = _response()
    noisy = replace(
        response.interval_response[0],
        oil_mass_delta=-5.57e-5,
    )
    example = TrainingExample(
        _input(),
        replace(response, interval_response=(noisy, *response.interval_response[1:])),
    )

    targets = _targets(example)

    assert targets[0, 0].item() == 0.0


def test_targets_reject_material_negative_values_with_field_name() -> None:
    response = _response()
    invalid = replace(response.interval_response[0], liquid_volume_delta=-0.01)
    example = TrainingExample(
        _input(),
        replace(response, interval_response=(invalid, *response.interval_response[1:])),
    )

    with pytest.raises(SurrogateModelError, match="liquid_volume_delta=-0.01"):
        _targets(example)


def test_targets_count_oil_backflow_as_zero_production() -> None:
    """Переток нефти обратно в пласт — не добыча и не ошибка разбора.

    Замер на прогоне 20260817T104426-70e8e055e519: у скважины 44 отрицательный
    COPR у 10 из 14 подключений, накопление падает на 3.53 т. Цель обнуляется,
    но интервал пересчитывается, чтобы доля перетоков была видна в отчёте.
    """

    response = _response()
    backflow = replace(response.interval_response[0], oil_mass_delta=-3.53)
    example = TrainingExample(
        _input(),
        replace(response, interval_response=(backflow, *response.interval_response[1:])),
    )
    stats: dict[str, int] = {}

    targets = _targets(example, stats)

    assert targets[0, 0].item() == 0.0
    assert stats["backflow_intervals"] == 1
    assert stats["backflow_worst_milli"] == -3530


def test_targets_reject_oil_negative_too_large_for_backflow() -> None:
    response = _response()
    absurd = replace(response.interval_response[0], oil_mass_delta=-2_000.0)
    example = TrainingExample(
        _input(),
        replace(response, interval_response=(absurd, *response.interval_response[1:])),
    )

    with pytest.raises(SurrogateModelError, match="oil_mass_delta=-2000.0"):
        _targets(example)


def test_scenario_split_never_splits_nodes_of_one_run() -> None:
    examples = tuple(_example(f"schedule-{index}") for index in range(10))
    train, validation, test = split_examples(examples)

    hashes = [
        {example.input.canonical_schedule_hash for example in split}
        for split in (train, validation, test)
    ]
    assert all(hashes)
    assert hashes[0].isdisjoint(hashes[1])
    assert hashes[0].isdisjoint(hashes[2])
    assert hashes[1].isdisjoint(hashes[2])


def test_candidate_with_changed_setpoint_is_scored_outside_domain() -> None:
    model = _model()
    original = _input()
    changed_node = replace(original.nodes[0], setpoint_m3_per_day=10_000.0)
    candidate = replace(
        original,
        canonical_schedule_hash="changed",
        nodes=(changed_node, *original.nodes[1:]),
    )

    prediction = model.predict(candidate)

    assert prediction.ood.score > 0.0
    assert prediction.ood.worst is not None
    assert prediction.ood.worst.well == changed_node.well


def test_money_weights_are_flat_when_alpha_is_zero() -> None:
    y = torch.tensor([[0.5, -1.0], [2.0, 0.0]])
    weights = _money_weights(
        y,
        scale=torch.tensor([1.0, 1.0]),
        mean=torch.tensor([0.0, 0.0]),
        rub_per_unit=torch.tensor([8360.0, -100.0]),
        alpha=0.0,
        cap=50.0,
    )
    assert torch.allclose(weights, torch.ones_like(y))


def test_money_weights_grow_with_physical_size_of_the_target() -> None:
    """Крупная скважина обязана весить больше мелкой: рубль линеен по объёму,
    а цель обучается в log1p, поэтому одинаковая относительная ошибка стоит
    разных денег."""
    y = torch.tensor([[0.0], [3.0]])
    weights = _money_weights(
        y,
        scale=torch.tensor([1.0]),
        mean=torch.tensor([0.0]),
        rub_per_unit=torch.tensor([8360.0]),
        alpha=1.0,
        cap=1e9,
    )
    assert float(weights[1, 0]) > float(weights[0, 0])
    assert float(weights[1, 0]) / float(weights[0, 0]) == pytest.approx(math.exp(3.0))


def test_money_weight_cap_bounds_the_heavy_tail() -> None:
    y = torch.tensor([[0.0], [20.0]])
    weights = _money_weights(
        y,
        scale=torch.tensor([1.0]),
        mean=torch.tensor([0.0]),
        rub_per_unit=torch.tensor([1.0]),
        alpha=1.0,
        cap=10.0,
    )
    assert float(weights.max()) <= 10.0


def test_spearman_matches_known_orderings() -> None:
    ascending = torch.tensor([1.0, 2.0, 3.0, 4.0])
    assert _spearman(ascending, ascending) == pytest.approx(1.0)
    assert _spearman(ascending, -ascending) == pytest.approx(-1.0)
    assert _spearman(ascending, torch.tensor([2.0, 1.0, 4.0, 3.0])) == pytest.approx(0.6)


def test_scenario_money_sums_signed_line_items_per_scenario() -> None:
    """Прокси обязан складывать статьи со знаком внутри каждого сценария."""
    shifted = torch.tensor([[1.0, 0.0], [0.0, 0.0], [1.0, 0.0]])
    totals = _scenario_money(
        shifted,
        torch.tensor([0, 0, 1]),
        2,
        scale=torch.tensor([1.0, 1.0]),
        mean=torch.tensor([0.0, 0.0]),
        rub_per_unit=torch.tensor([8360.0, -100.0]),
    )
    unit = math.expm1(1.0) * 8360.0
    assert totals[0].item() == pytest.approx(unit)
    assert totals[1].item() == pytest.approx(unit)
    negative = _scenario_money(
        torch.tensor([[0.0, 1.0]]),
        torch.tensor([0]),
        1,
        scale=torch.tensor([1.0, 1.0]),
        mean=torch.tensor([0.0, 0.0]),
        rub_per_unit=torch.tensor([8360.0, -100.0]),
    )
    assert negative[0].item() == pytest.approx(-math.expm1(1.0) * 100.0)


def test_watercut_parameterization_round_trips_oil_exactly() -> None:
    """Нефть, выведенная из жидкости и обводнённости, обязана совпасть с фактом.

    Это и есть смысл контрактного требования §5.1: жидкость и нефть перестают
    быть двумя независимыми предсказаниями, которые могут разойтись.
    """
    density = 0.9131
    raw = {
        "oil_mass_delta": 50.0,
        "liquid_volume_delta": 200.0,
        "injection_volume_delta": 0.0,
        "liquid_rate": 7.0,
        "injection_rate": 0.0,
        "bhp": 75.0,
    }
    row = _watercut_row(raw, oil_density_t_per_m3=density)
    liquid, watercut = row[0], row[1]
    assert liquid == pytest.approx(200.0)
    restored_oil = liquid * (1.0 - watercut) * density
    assert restored_oil == pytest.approx(raw["oil_mass_delta"])


def test_watercut_is_zero_when_no_liquid_flows() -> None:
    raw = dict.fromkeys(
        (
            "oil_mass_delta",
            "liquid_volume_delta",
            "injection_volume_delta",
            "liquid_rate",
            "injection_rate",
            "bhp",
        ),
        0.0,
    )
    raw["injection_volume_delta"] = 400.0
    row = _watercut_row(raw, oil_density_t_per_m3=0.9131)
    assert row[1] == 0.0
    assert row[0] * (1.0 - row[1]) * 0.9131 == 0.0


def test_watercut_targets_survive_the_full_encode_decode_path() -> None:
    """Полный путь: отклик → цели → log1p → скейлер → expm1 → нефть."""
    density = 0.9131
    example = _example()
    encoded = _targets(
        example, parameterization="watercut", oil_density_t_per_m3=density
    )
    scaler = Standardizer.fit(encoded)
    decoded = torch.expm1(scaler.inverse(scaler.transform(encoded))).clamp_min(0.0)
    interval = {
        (row.well, row.control_step): row
        for row in example.response.interval_response
    }
    for node, values in zip(example.input.nodes, decoded.tolist()):
        liquid, watercut = values[0], values[1]
        fact = interval[(node.well, node.control_step)]
        restored = liquid * (1.0 - min(watercut, 1.5)) * density
        assert restored == pytest.approx(fact.oil_mass_delta, abs=1e-2)
        assert liquid == pytest.approx(fact.liquid_volume_delta, abs=1e-2)


def test_new_config_fields_do_not_invalidate_an_existing_checkpoint(tmp_path) -> None:
    """Отпечаток сверяется с конфигом из файла, а не с текущим `ModelConfig`.

    Иначе любое поле, добавленное в `ModelConfig` с умолчанием, меняет
    `_fingerprint` и объявляет повреждённой каждую ранее обученную модель —
    включая `model-task34-700`, на котором держатся G5 и G7. Тест
    воспроизводит ровно это: checkpoint, записанный до появления полей
    денежного лосса, обязан грузиться после их появления.
    """

    model = _model()
    saved = model.save(tmp_path / "surrogate.pt")
    payload = torch.load(saved, map_location="cpu", weights_only=False)

    older = {
        name: value
        for name, value in payload["config"].items()
        if name
        not in {
            "money_rub_per_unit",
            "money_weight_alpha",
            "money_weight_cap",
            "lr_schedule",
            "select_by",
            "target_parameterization",
            "oil_density_t_per_m3",
        }
    }
    assert len(older) < len(payload["config"])
    payload["config"] = older
    payload["version"] = model._fingerprint(older)
    torch.save(payload, saved)

    restored = TrajectorySurrogate.load(saved)
    assert restored.version == payload["version"]
    assert restored.predict(_input()).output.nodes[0] == model.predict(_input()).output.nodes[0]
