"""Приёмка задачи 36 (docs/v1/assignments/andrey.md, docs/context/08_contracts.md §5.5).

Карточка: «Бьёт CRM по ранговой корреляции; отдельно проверяет `ACTIVE/SHUT`,
переходы, пороги ЭЦН, денежную ошибку событий/CAPEX, F1 `BHP_LIMITED` и
ошибку BHP».

Здесь проверяется **сам измерительный инструмент**, а не качество модели:
что метрика на известном ответе даёт этот ответ, что гейт по CRM отвергает
не бьющую базовую линию модель и что денежные метрики считаются теми же
автоматами, что считают деньги в экономике, а не своей копией правил.
Качество обученной модели меряется на настоящем датасете (задача 34) и в
этом файле не утверждается ни разу.

Траектории ниже — сконструированные, с известным ответом. Это не «синтетика
в метриках качества» (правило 4): проверяется формула, а не модель, и
`accept_against_baseline` отдельным тестом обязан отказаться выносить
вердикт, если ему сказали, что вход синтетический.
"""

from __future__ import annotations

import pytest

from contracts import (
    DEFAULT_NORMATIVES_2007,
    ActiveControlMode,
    ChargeInitialEsp,
    EspCatalogEntry,
    IntervalResponse,
    NormativeSet,
    Policies,
    QuantizationPolicy,
    StateAtDate,
)

from surrogate.metrics import (
    MetricsError,
    WellTrajectory,
    accept_against_baseline,
    ranking_metrics,
    state_metrics,
    watercut_metrics,
)

ESP_CATALOG: tuple[EspCatalogEntry, ...] = (
    EspCatalogEntry(nominal=20.0, interval_low=0.0, interval_high=25.0, cost_rub=900_000.0),
    EspCatalogEntry(nominal=45.0, interval_low=25.0, interval_high=60.0, cost_rub=1_400_000.0),
    EspCatalogEntry(nominal=80.0, interval_low=60.0, interval_high=95.0, cost_rub=2_100_000.0),
    EspCatalogEntry(nominal=125.0, interval_low=95.0, interval_high=160.0, cost_rub=3_300_000.0),
)

NORMATIVES = NormativeSet(esp_catalog=ESP_CATALOG, **DEFAULT_NORMATIVES_2007)
POLICIES = Policies(
    charge_initial_esp=ChargeInitialEsp.NOT_CHARGED,
    quantization_policy=QuantizationPolicy.STEP_5,
)
OIL_DENSITY = 0.9131

N_STATES = 6
N_INTERVALS = 4


def _state(
    index: int,
    well: str,
    *,
    liquid: float = 0.0,
    injection: float = 0.0,
    bhp: float = 120.0,
    mode: ActiveControlMode = ActiveControlMode.RATE_TARGET,
) -> StateAtDate:
    return StateAtDate(
        deck_date_index=index,
        well=well,
        liquid_rate=liquid,
        oil_rate=liquid * 0.5,
        injection_rate=injection,
        thp=40.0,
        bhp=bhp,
        well_efficiency=1.0,
        active_control_mode=mode,
    )


def _response(step: int, well: str, *, oil: float = 100.0, liquid: float = 200.0) -> IntervalResponse:
    return IntervalResponse(
        control_step=step,
        well=well,
        oil_mass_delta=oil,
        liquid_volume_delta=liquid,
        injection_volume_delta=0.0,
    )


def _trajectory(well: str, rates: list[float], **kwargs) -> WellTrajectory:
    modes = kwargs.pop("modes", None)
    bhps = kwargs.pop("bhps", None)
    states = tuple(
        _state(
            i,
            well,
            liquid=rate,
            bhp=120.0 if bhps is None else bhps[i],
            mode=(
                ActiveControlMode.RATE_TARGET if modes is None else modes[i]
            ),
        )
        for i, rate in enumerate(rates)
    )
    responses = tuple(_response(k, well) for k in range(N_INTERVALS))
    return WellTrajectory(well=well, states=states, responses=responses)


# --- Ранжирование по ЧДД ---------------------------------------------------


def test_perfect_ordering_gives_correlation_one_and_zero_regret() -> None:
    actual = [10.0, 20.0, 30.0, 40.0, 50.0]
    predicted = [1.0, 2.0, 3.0, 4.0, 5.0]  # другой масштаб, тот же порядок

    metrics = ranking_metrics(actual, predicted, k_values=(1, 3))

    assert metrics.spearman_rank_correlation == pytest.approx(1.0)
    assert metrics.precision_at_k == {1: 1.0, 3: 1.0}
    assert metrics.regret_at_k_rub == {1: 0.0, 3: 0.0}


def test_reversed_ordering_gives_correlation_minus_one() -> None:
    actual = [10.0, 20.0, 30.0, 40.0, 50.0]
    predicted = [5.0, 4.0, 3.0, 2.0, 1.0]

    metrics = ranking_metrics(actual, predicted, k_values=(1,))

    assert metrics.spearman_rank_correlation == pytest.approx(-1.0)
    assert metrics.precision_at_k[1] == 0.0
    # Модель назвала лучшим худшего: теряется вся разница между ними.
    assert metrics.regret_at_k_rub[1] == pytest.approx(40.0)


def test_mae_can_be_perfect_while_the_ordering_is_useless() -> None:
    """Ровно та причина, по которой сдаваемая метрика ранговая, а не MAE
    (§5.2): сдвиг на константу не портит MAE-порядок величин, но
    перестановка соседей рушит решение оптимизатора."""

    actual = [100.0, 101.0, 102.0, 300.0]
    predicted = [102.0, 101.0, 100.0, 300.0]  # ошибка не больше 2 руб

    metrics = ranking_metrics(actual, predicted, k_values=(1, 2))

    assert max(abs(a - p) for a, p in zip(actual, predicted)) <= 2.0
    assert metrics.spearman_rank_correlation < 1.0
    # При этом настоящий лучший всё же найден — regret@1 нулевой, и это
    # именно то, что regret обязан показывать отдельно от корреляции.
    assert metrics.regret_at_k_rub[1] == 0.0


def test_precision_at_k_counts_set_overlap_not_order_inside() -> None:
    """Внутри среза порядок не важен: оптимизатор пересчитывает срез
    настоящим прогоном, ему нужен состав, а не расстановка внутри."""

    actual = [50.0, 40.0, 30.0, 20.0, 10.0]
    predicted = [40.0, 50.0, 30.0, 10.0, 20.0]  # первые два переставлены

    metrics = ranking_metrics(actual, predicted, k_values=(2,))

    assert metrics.precision_at_k[2] == 1.0
    assert metrics.regret_at_k_rub[2] == 0.0


def test_regret_is_measured_in_roubles_not_in_ranks() -> None:
    """Одинаковая перестановка рангов стоит разных денег — метрика обязана
    это различать, иначе цена ошибки теряется."""

    cheap = ranking_metrics([100.0, 99.0, 1.0], [99.0, 100.0, 1.0], k_values=(1,))
    costly = ranking_metrics([100.0, 1.0, 0.5], [1.0, 100.0, 0.5], k_values=(1,))

    assert cheap.spearman_rank_correlation == pytest.approx(
        costly.spearman_rank_correlation
    )
    assert cheap.regret_at_k_rub[1] == pytest.approx(1.0)
    assert costly.regret_at_k_rub[1] == pytest.approx(99.0)


def test_k_larger_than_the_sample_is_dropped_not_silently_clipped() -> None:
    metrics = ranking_metrics([1.0, 2.0, 3.0], [1.0, 2.0, 3.0], k_values=(1, 3, 10))

    assert set(metrics.precision_at_k) == {1, 3}


def test_mismatched_lengths_are_rejected() -> None:
    with pytest.raises(MetricsError):
        ranking_metrics([1.0, 2.0], [1.0, 2.0, 3.0])


def test_single_candidate_is_rejected() -> None:
    """Моков нет: ранжирование одного кандидата не определено, и метрика
    обязана это сказать, а не вернуть 1.0."""

    with pytest.raises(MetricsError):
        ranking_metrics([1.0], [1.0])


# --- Гейт по CRM -----------------------------------------------------------


def _ranking(spearman_target: list[float], predicted: list[float]):
    return ranking_metrics(spearman_target, predicted, k_values=(1,))


def test_model_beating_crm_is_accepted() -> None:
    actual = [1.0, 2.0, 3.0, 4.0, 5.0]
    model = _ranking(actual, [1.0, 2.0, 3.0, 4.0, 5.0])  # корреляция 1.0
    crm = _ranking(actual, [1.0, 2.0, 3.0, 5.0, 4.0])  # ниже

    verdict = accept_against_baseline(model, crm)

    assert verdict.accepted is True
    assert verdict.margin > 0.0
    assert "выше" in verdict.reason


def test_model_not_beating_crm_is_rejected() -> None:
    """«Любая модель обязана бить CRM по ранговой корреляции, иначе
    отвергается» (§5.5) — исполняемая форма, а не отчётная строка."""

    actual = [1.0, 2.0, 3.0, 4.0, 5.0]
    model = _ranking(actual, [5.0, 4.0, 3.0, 2.0, 1.0])
    crm = _ranking(actual, [1.0, 2.0, 3.0, 4.0, 5.0])

    verdict = accept_against_baseline(model, crm)

    assert verdict.accepted is False
    assert "отвергается" in verdict.reason


def test_tie_with_crm_is_rejected_not_accepted() -> None:
    """Равенство базовой линии — не основание её менять: модель дороже в
    обучении и непрозрачнее, а даёт то же самое."""

    actual = [1.0, 2.0, 3.0, 4.0, 5.0]
    same = [1.0, 2.0, 3.0, 4.0, 5.0]
    verdict = accept_against_baseline(_ranking(actual, same), _ranking(actual, same))

    assert verdict.accepted is False
    assert verdict.margin == 0.0


def test_comparison_on_different_samples_is_rejected() -> None:
    """Гейт сравнивает CRM и модель на одном holdout: иначе «бьёт» ничего
    не значит."""

    model = ranking_metrics([1.0, 2.0, 3.0], [1.0, 2.0, 3.0])
    crm = ranking_metrics([1.0, 2.0, 3.0, 4.0], [1.0, 2.0, 3.0, 4.0])

    with pytest.raises(MetricsError):
        accept_against_baseline(model, crm)


def test_synthetic_inputs_block_the_verdict_entirely() -> None:
    """Правило 4 репозитория: синтетика не может быть предъявлена как замер
    качества. Гейт отказывается принимать модель, даже когда числа хорошие."""

    actual = [1.0, 2.0, 3.0, 4.0, 5.0]
    model = _ranking(actual, actual)
    crm = _ranking(actual, [5.0, 4.0, 3.0, 2.0, 1.0])

    verdict = accept_against_baseline(model, crm, synthetic_inputs=True)

    assert verdict.accepted is False
    assert "синтетик" in verdict.reason


# --- StateAtDate: ACTIVE/SHUT, переходы, ЭЦН, деньги, BHP ------------------


def test_identical_trajectories_give_perfect_state_metrics() -> None:
    rates = [0.0, 50.0, 50.0, 50.0, 50.0, 50.0]
    fact = _trajectory("W1", rates)
    model = _trajectory("W1", rates)

    metrics = state_metrics([model], [fact], normatives=NORMATIVES, policies=POLICIES)

    assert metrics.active_shut_accuracy == 1.0
    assert metrics.fund_state_accuracy == 1.0
    assert metrics.transition_precision == 1.0
    assert metrics.transition_recall == 1.0
    assert metrics.esp_nominal_accuracy == 1.0
    assert metrics.esp_capex_absolute_error_rub == 0.0
    assert metrics.event_cost_absolute_error_rub == 0.0
    assert metrics.bhp_mae_bar == 0.0
    assert metrics.money_absolute_error_rub == 0.0


def test_confusing_active_with_shut_is_caught() -> None:
    """«Суррогат путает работает и остановлена» — строка §5.5. Ошибка на
    одном шаге из шести обязана быть видна в точности, а не утонуть."""

    fact = _trajectory("W1", [0.0, 50.0, 50.0, 50.0, 50.0, 50.0])
    model = _trajectory("W1", [0.0, 50.0, 50.0, 0.0, 50.0, 50.0])

    metrics = state_metrics([model], [fact], normatives=NORMATIVES, policies=POLICIES)

    assert metrics.active_shut_accuracy == pytest.approx(5.0 / 6.0)
    assert metrics.fund_state_accuracy == pytest.approx(5.0 / 6.0)


def test_false_transition_costs_real_money_and_is_measured() -> None:
    """Ложный переход PROD_ACTIVE → SHUT → PROD_ACTIVE стоит событийных
    затрат. Метрика обязана показать разницу в рублях, а не только в долях."""

    fact = _trajectory("W1", [0.0, 50.0, 50.0, 50.0, 50.0, 50.0])
    model = _trajectory("W1", [0.0, 50.0, 50.0, 0.0, 50.0, 50.0])

    metrics = state_metrics([model], [fact], normatives=NORMATIVES, policies=POLICIES)

    assert metrics.event_cost_absolute_error_rub > 0.0
    # Модель насчитала лишние переходы — знаковая ошибка положительна.
    assert metrics.event_cost_signed_error_rub > 0.0
    assert metrics.transition_recall == 1.0
    assert metrics.transition_precision < 1.0


def test_esp_size_error_is_counted_at_the_catalog_boundary_only() -> None:
    """Промах внутри интервала каталога ничего не стоит, промах мимо границы
    стоит разницы CAPEX — метрика ловит второе, а не отклонение дебита."""

    # 30 и 40 м³/сут — оба в интервале 25…60, типоразмер один и тот же.
    inside = state_metrics(
        [_trajectory("W1", [0.0, 30.0, 30.0, 30.0, 30.0, 30.0])],
        [_trajectory("W1", [0.0, 40.0, 40.0, 40.0, 40.0, 40.0])],
        normatives=NORMATIVES,
        policies=POLICIES,
    )
    assert inside.esp_nominal_accuracy == 1.0

    # 24 и 30 отличаются меньше, но лежат по разные стороны границы 25.
    across = state_metrics(
        [_trajectory("W1", [0.0, 24.0, 24.0, 24.0, 24.0, 24.0])],
        [_trajectory("W1", [0.0, 30.0, 30.0, 30.0, 30.0, 30.0])],
        normatives=NORMATIVES,
        policies=POLICIES,
    )
    assert across.esp_nominal_accuracy < 1.0


def test_esp_money_error_comes_from_the_real_state_machine() -> None:
    """Денежная ошибка ЭЦН считается прогоном `EspStateMachine` по обеим
    траекториям, а не формулой рядом: своя копия правил разошлась бы с
    Методикой молча (правило 5)."""

    fact = _trajectory("W1", [0.0, 30.0, 30.0, 30.0, 30.0, 30.0])
    # Рост дебита за границу 60 заставляет автомат сменить типоразмер вверх.
    model = _trajectory("W1", [0.0, 30.0, 30.0, 90.0, 90.0, 90.0])

    metrics = state_metrics([model], [fact], normatives=NORMATIVES, policies=POLICIES)

    assert metrics.esp_capex_absolute_error_rub > 0.0
    assert metrics.esp_capex_signed_error_rub > 0.0


def test_signed_and_absolute_money_errors_are_reported_separately() -> None:
    """Систематический недосчёт и систематический пересчёт — разные дефекты;
    модуль складывает их в неразличимую кучу, знак — нет.

    Зеркало предыдущего теста: там замену придумала модель, здесь она её
    проспала. Первичное оснащение при `NOT_CHARGED` не начисляется вовсе
    (CLAUDE.md), поэтому CAPEX появляется только на смене типоразмера — две
    плоские траектории на разных дебитах дали бы ноль у обеих.
    """

    fact = _trajectory("W1", [0.0, 30.0, 30.0, 90.0, 90.0, 90.0])
    model = _trajectory("W1", [0.0, 30.0, 30.0, 30.0, 30.0, 30.0])

    metrics = state_metrics([model], [fact], normatives=NORMATIVES, policies=POLICIES)

    assert metrics.esp_capex_absolute_error_rub > 0.0
    assert metrics.esp_capex_signed_error_rub < 0.0


def test_bhp_limited_f1_catches_the_missed_infeasibility() -> None:
    """«Суррогат не видит недостижимость — прямая причина ловушки §5.1.1».
    Модель, никогда не сказавшая BHP_LIMITED, обязана получить F1 = 0 при
    ненулевой accuracy: одна accuracy этот дефект прячет."""

    limited = [ActiveControlMode.BHP_LIMITED] * 2 + [ActiveControlMode.RATE_TARGET] * 4
    never = [ActiveControlMode.RATE_TARGET] * 6
    rates = [50.0] * 6

    metrics = state_metrics(
        [_trajectory("W1", rates, modes=never)],
        [_trajectory("W1", rates, modes=limited)],
        normatives=NORMATIVES,
        policies=POLICIES,
    )

    assert metrics.bhp_limited_f1 == 0.0
    assert metrics.bhp_limited_accuracy == pytest.approx(4.0 / 6.0)


def test_bhp_limited_f1_is_one_when_the_mode_is_predicted_exactly() -> None:
    modes = [ActiveControlMode.BHP_LIMITED] * 3 + [ActiveControlMode.RATE_TARGET] * 3
    rates = [50.0] * 6

    metrics = state_metrics(
        [_trajectory("W1", rates, modes=modes)],
        [_trajectory("W1", rates, modes=modes)],
        normatives=NORMATIVES,
        policies=POLICIES,
    )

    assert metrics.bhp_limited_f1 == pytest.approx(1.0)


def test_bhp_error_is_measured_in_bar() -> None:
    rates = [50.0] * 6
    fact_bhp = [100.0] * 6
    model_bhp = [103.0, 97.0, 100.0, 100.0, 100.0, 100.0]

    metrics = state_metrics(
        [_trajectory("W1", rates, bhps=model_bhp)],
        [_trajectory("W1", rates, bhps=fact_bhp)],
        normatives=NORMATIVES,
        policies=POLICIES,
    )

    assert metrics.bhp_mae_bar == pytest.approx(6.0 / 6.0)


def test_wells_are_paired_by_name_not_by_position() -> None:
    rates = [0.0, 50.0, 50.0, 50.0, 50.0, 50.0]
    fact = [_trajectory("W1", rates), _trajectory("W2", rates)]
    model = [_trajectory("W2", rates), _trajectory("W1", rates)]

    metrics = state_metrics(model, fact, normatives=NORMATIVES, policies=POLICIES)

    assert metrics.active_shut_accuracy == 1.0


def test_unknown_well_is_rejected() -> None:
    rates = [0.0, 50.0, 50.0, 50.0, 50.0, 50.0]
    with pytest.raises(MetricsError):
        state_metrics(
            [_trajectory("GHOST", rates)],
            [_trajectory("W1", rates)],
            normatives=NORMATIVES,
            policies=POLICIES,
        )


def test_trajectory_without_history_is_rejected() -> None:
    """Храповик ЭЦН требует прокрутки истории с начала данных: ряд, где дат
    дека не больше числа интервалов, автоматом не считается."""

    with pytest.raises(MetricsError):
        WellTrajectory(
            well="W1",
            states=tuple(_state(i, "W1", liquid=50.0) for i in range(N_INTERVALS)),
            responses=tuple(_response(k, "W1") for k in range(N_INTERVALS)),
        )


def test_negative_rule_exclusion_is_applied_to_the_esp_machine() -> None:
    """Правило исключения отрицательного месячного прироста обязательно даже
    там, где собственные приросты неотрицательны (CLAUDE.md, докстринг
    `is_excluded_by_negative_rule`) — траектория обязана его вычислять."""

    states = tuple(_state(i, "W1", liquid=50.0) for i in range(N_STATES))
    responses = (
        _response(0, "W1"),
        _response(1, "W1", oil=-5.0),
        _response(2, "W1"),
        _response(3, "W1"),
    )
    track = WellTrajectory(well="W1", states=states, responses=responses)

    excluded = track.excluded_deck_steps()

    assert excluded == frozenset({track.first_interval_end_deck_step + 1})


# --- Обводнённость: диагностика, не отбраковка -----------------------------


def test_watercut_error_is_measured() -> None:
    actual = [_response(k, "W1", oil=100.0, liquid=200.0) for k in range(4)]
    predicted = [_response(k, "W1", oil=100.0, liquid=200.0) for k in range(4)]

    metrics = watercut_metrics(actual, predicted, oil_density_t_per_m3=OIL_DENSITY)

    assert metrics.mae == pytest.approx(0.0)
    assert metrics.n_points == 4


def test_falling_watercut_is_reported_but_does_not_reject() -> None:
    """§5.5, исправление 14.08: монотонность обводнённости — не жёсткий
    oracle. Метрика считает долю падений и отдаёт её человеку; вердикт
    приёмки её не видит вовсе."""

    actual = [_response(k, "W1", oil=100.0, liquid=200.0) for k in range(4)]
    # Обводнённость падает: доля нефти в жидкости растёт.
    predicted = [
        _response(0, "W1", oil=100.0, liquid=200.0),
        _response(1, "W1", oil=120.0, liquid=200.0),
        _response(2, "W1", oil=140.0, liquid=200.0),
        _response(3, "W1", oil=160.0, liquid=200.0),
    ]

    metrics = watercut_metrics(actual, predicted, oil_density_t_per_m3=OIL_DENSITY)

    assert metrics.share_of_drops == pytest.approx(1.0)
    assert metrics.mae > 0.0

    # И при этом вердикт приёмки про обводнённость ничего не знает: его
    # поля — только ранговая корреляция модели и базовой линии.
    verdict = accept_against_baseline(
        ranking_metrics([1.0, 2.0, 3.0], [1.0, 2.0, 3.0]),
        ranking_metrics([1.0, 2.0, 3.0], [3.0, 2.0, 1.0]),
    )
    assert verdict.accepted is True


def test_axis_mismatch_between_fact_and_prediction_is_rejected() -> None:
    actual = [_response(0, "W1"), _response(1, "W1")]
    predicted = [_response(0, "W1"), _response(1, "W2")]

    with pytest.raises(MetricsError):
        watercut_metrics(actual, predicted, oil_density_t_per_m3=OIL_DENSITY)


def test_npv_calibration_removes_bias_and_compression() -> None:
    """Аффинное преобразование монотонно, поэтому порядок сценариев не меняет,
    а смещение и сжатие снимает полностью."""
    from surrogate.train import npv_calibration

    actual = [1.0e10, 1.1e10, 1.2e10, 1.3e10]
    # Сжато втрое и смещено на −2e9 — как у обученной с ранговым членом модели.
    predicted = [9.0e9 + (value - 1.15e10) / 3.0 for value in actual]
    a, b = npv_calibration(actual, predicted)
    fixed = [a + b * value for value in predicted]
    for got, want in zip(fixed, actual):
        assert got == pytest.approx(want, rel=1e-9)
    order_before = sorted(range(4), key=lambda i: predicted[i])
    order_after = sorted(range(4), key=lambda i: fixed[i])
    assert order_before == order_after


def test_npv_calibration_rejects_degenerate_predictions() -> None:
    from surrogate.train import TrainingCommandError, npv_calibration

    with pytest.raises(TrainingCommandError, match="вырождены"):
        npv_calibration([1.0, 2.0, 3.0], [5.0, 5.0, 5.0])
