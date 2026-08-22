"""Приёмка задачи 39 (docs/v1/assignments/andrey.md, docs/context/08_contracts.md §10.1–10.3).

Карточка: «таблица "предсказано против факта" по всем кандидатам
сохраняется — это сдаваемые метрики суррогата; лучший кандидат цикла
переоценивается **последней версией модели** и несёт `self_consistent`.
**Это внутренний выбор кандидата, не источник сдаваемого числа** — за него
отвечает задача 62».

Четыре части приёмки:

1. схема раунда §10.1 исполняется — top-k, прогон, расширение или сужение
   области, дообучение только на разошедшемся раунде;
2. область доверия работает как ограничение, а не как отбор постфактум:
   кандидат с `ood_score > τ` не попадает в top-k вовсе;
3. таблица §10.3 сохраняется целиком, включая разошедшиеся раунды;
4. переоценка сделана **последней** версией суррогата, и цикл структурно
   не может выдать сдаваемое число.

Суррогат и истина здесь — настоящие вычисляемые функции от θ с известным
ответом, а не заглушки: цикл действительно ищет по ним, а тест знает, где
они расходятся.
"""

from __future__ import annotations

import ast
from dataclasses import fields
from pathlib import Path

import pytest

from backend.core.contracts import Theta

from backend.application.optimization.verification import (
    CandidateCheck,
    SurrogateVerdict,
    TruthVerdict,
    VerificationError,
    VerificationReport,
    run_verification_loop,
    trust_region_objective,
)

ROOT = Path(__file__).resolve().parent.parent

BOUNDS = {"x": (0.0, 100.0)}


def _theta(value: float = 1.0) -> Theta:
    return Theta(values={"x": value}, bounds=dict(BOUNDS))


class _Surrogate:
    """ЧДД растёт с x; `ood_score` растёт с удалением от обучающей точки.

    Настоящая функция: оптимизатор ищет по ней максимум, а область доверия
    ограничивает, насколько далеко он вправе уйти.
    """

    def __init__(self, version: int = 1, *, bias: float = 0.0, centre: float = 0.0) -> None:
        self.version = version
        self.bias = bias
        self.centre = centre
        self.calls: list[Theta] = []

    def __call__(self, theta: Theta) -> SurrogateVerdict:
        self.calls.append(theta)
        x = theta.values["x"]
        return SurrogateVerdict(
            predicted_npv=100.0 * x + self.bias,
            ood_score=abs(x - self.centre) / 10.0,
        )


class _Truth:
    """Истина: тот же рост, но без смещения суррогата."""

    def __init__(self) -> None:
        self.calls: list[Theta] = []

    def __call__(self, theta: Theta) -> TruthVerdict:
        self.calls.append(theta)
        x = theta.values["x"]
        self.calls_count = len(self.calls)
        return TruthVerdict(
            npv=100.0 * x,
            run_id=f"run-{len(self.calls):04d}",
            canonical_schedule_hash="c" * 64,
        )


class _Retrainer:
    """Дообучение: каждая новая версия сдвигает смещение к нулю."""

    def __init__(self, produce: list[_Surrogate]) -> None:
        self.produce = produce
        self.observations: list[tuple[CandidateCheck, ...]] = []

    def __call__(self, observations: tuple[CandidateCheck, ...]) -> _Surrogate:
        self.observations.append(observations)
        return self.produce.pop(0)


def _tolerance(limit: float):
    """Критерий «сошлось»: относительное отклонение не больше `limit`.

    Задача 40 меряет, каким критерий должен быть (§10.4 оставляет это
    незамеренным); здесь он подаётся снаружи именно поэтому — цикл не
    вправе выбирать его за задачу 40.
    """

    def criterion(checks) -> bool:
        return all(abs(check.relative_deviation) <= limit for check in checks)

    return criterion


def _loop(**kwargs):
    defaults = dict(
        seed=7,
        initial_tau=1.0,
        runs_per_round=3,
        max_rounds=2,
        optimizer_evaluations_per_round=60,
    )
    defaults.update(kwargs)
    return run_verification_loop(**defaults)


# --- 1. Схема раунда §10.1 --------------------------------------------------


def test_converged_round_expands_the_trust_region() -> None:
    surrogate = _Surrogate()
    report = _loop(
        surrogate=surrogate,
        truth=_Truth(),
        retrain=_Retrainer([]),
        criterion=_tolerance(0.5),
        start_theta=_theta(),
    )

    first = report.rounds[0]
    assert first.converged is True
    assert first.next_tau > first.tau
    assert first.retrained is False


def test_diverged_round_contracts_the_region_and_retrains() -> None:
    """«разошлось → область сужается, k прогонов уходят в обучающую
    выборку, суррогат дообучается» — все три следствия сразу."""

    surrogate = _Surrogate(version=1, bias=1_000_000.0)
    next_version = _Surrogate(version=2, bias=0.0)
    retrainer = _Retrainer([next_version])

    report = _loop(
        surrogate=surrogate,
        truth=_Truth(),
        retrain=retrainer,
        criterion=_tolerance(0.001),
        start_theta=_theta(),
        max_rounds=1,
    )

    first = report.rounds[0]
    assert first.converged is False
    assert first.next_tau < first.tau
    assert first.retrained is True
    # Дообучение получило ровно наблюдения этого раунда, не всю историю.
    assert len(retrainer.observations) == 1
    assert retrainer.observations[0] == first.checks


def test_retraining_happens_only_on_a_diverged_round() -> None:
    retrainer = _Retrainer([])
    _loop(
        surrogate=_Surrogate(),
        truth=_Truth(),
        retrain=retrainer,
        criterion=_tolerance(0.5),
        start_theta=_theta(),
    )

    assert retrainer.observations == []


def test_number_of_runs_per_round_is_the_budget_not_a_guess() -> None:
    """k — это `Budgets.runs_per_verification_round`: каждый прогон стоит
    513 с на реальном Model_Z, поэтому он задаётся, а не подбирается."""

    truth = _Truth()
    report = _loop(
        surrogate=_Surrogate(),
        truth=truth,
        retrain=_Retrainer([]),
        criterion=_tolerance(0.5),
        start_theta=_theta(),
        runs_per_round=2,
        max_rounds=3,
    )

    assert all(len(round_report.checks) <= 2 for round_report in report.rounds)
    assert len(truth.calls) == report.total_runs


# --- 2. Область доверия — ограничение, а не отбор постфактум ---------------


def test_candidates_outside_the_region_never_reach_the_simulator() -> None:
    """Ключевое отличие от отбора постфактум: прогон стоит денег, и
    кандидат вне области не должен до него доезжать."""

    surrogate = _Surrogate(centre=0.0)
    truth = _Truth()
    tau = 1.0  # ood_score = |x| / 10 ⇒ допустимо x ≤ 10

    _loop(
        surrogate=surrogate,
        truth=truth,
        retrain=_Retrainer([]),
        criterion=_tolerance(0.5),
        start_theta=_theta(),
        initial_tau=tau,
        max_rounds=1,
    )

    assert truth.calls, "истина не вызывалась вовсе"
    for theta in truth.calls:
        assert theta.values["x"] <= 10.0 + 1e-9, theta.values


def test_trust_region_is_expressed_as_infeasibility_not_as_a_correction() -> None:
    """Выход за область снимает `feasible` и пишет нарушение; предсказанный
    ЧДД при этом не трогается — иначе ограничение стало бы поправкой."""

    surrogate = _Surrogate(centre=0.0)
    objective = trust_region_objective(surrogate, tau=1.0)

    inside = objective(_theta(5.0))
    outside = objective(_theta(50.0))

    assert inside.feasible is True
    assert inside.violations_by_scenario == ()

    assert outside.feasible is False
    assert outside.violations_by_scenario
    assert outside.violations_by_scenario[0].scenario_id == "trust_region"
    # ЧДД остался тем, что сказал суррогат, без поправки на выход за область.
    assert outside.objective == pytest.approx(100.0 * 50.0)


def test_provenance_binds_the_prediction_to_a_surrogate_version_and_tau() -> None:
    surrogate = _Surrogate(version=3)
    result = trust_region_objective(surrogate, tau=2.0)(_theta(1.0))

    assert result.provenance["surrogate_version"] == "3"
    assert float(result.provenance["tau"]) == pytest.approx(2.0)


def test_empty_trust_region_stops_the_loop_instead_of_pretending() -> None:
    """Если внутри области не нашлось ни одного кандидата, раунд не
    состоялся. Притворяться, что состоялся, — то же самое, что мок."""

    surrogate = _Surrogate(centre=1_000.0)  # вся область далеко от границ θ

    with pytest.raises(VerificationError, match="ни одного раунда"):
        _loop(
            surrogate=surrogate,
            truth=_Truth(),
            retrain=_Retrainer([]),
            criterion=_tolerance(0.5),
            start_theta=_theta(),
            initial_tau=0.0,
        )


# --- 3. Таблица §10.3 -------------------------------------------------------


def test_table_covers_every_checked_candidate_in_order() -> None:
    """«Таблица предсказанный ЧДД против фактического по всем проверенным
    кандидатам и есть метрики качества суррогата, требуемые к сдаче»."""

    truth = _Truth()
    report = _loop(
        surrogate=_Surrogate(),
        truth=truth,
        retrain=_Retrainer([]),
        criterion=_tolerance(0.5),
        start_theta=_theta(),
        max_rounds=3,
    )

    assert report.total_runs == len(truth.calls)
    assert [check.run_id for check in report.table] == [
        f"run-{i:04d}" for i in range(1, len(truth.calls) + 1)
    ]
    for check in report.table:
        assert check.predicted_npv is not None
        assert check.actual_npv is not None
        assert check.canonical_schedule_hash


def test_diverged_rounds_stay_in_the_table() -> None:
    """Выбрасывать неудачные раунды значило бы отчитываться по подобранной
    подвыборке — метрики сдаются по всем проверенным кандидатам."""

    surrogate = _Surrogate(version=1, bias=1_000_000.0)
    # Оба раунда расходятся, значит дообучение случится дважды — версий
    # в очереди столько же, сколько раундов.
    retrainer = _Retrainer(
        [
            _Surrogate(version=2, bias=1_000_000.0),
            _Surrogate(version=3, bias=1_000_000.0),
        ]
    )

    report = _loop(
        surrogate=surrogate,
        truth=_Truth(),
        retrain=retrainer,
        criterion=_tolerance(0.0),
        start_theta=_theta(),
        max_rounds=2,
    )

    assert report.converged_rounds == 0
    assert report.total_runs > 0
    assert len(report.table) == sum(len(r.checks) for r in report.rounds)


def test_deviation_is_signed_prediction_minus_fact() -> None:
    check = CandidateCheck(
        round_index=0,
        theta=_theta(),
        predicted_npv=110.0,
        actual_npv=100.0,
        ood_score=0.0,
        tau=1.0,
        surrogate_version=1,
        run_id="run-0001",
        canonical_schedule_hash="c" * 64,
    )

    assert check.deviation == pytest.approx(10.0)
    assert check.relative_deviation == pytest.approx(0.1)


def test_zero_actual_npv_is_an_error_not_a_silent_ratio() -> None:
    check = CandidateCheck(
        round_index=0,
        theta=_theta(),
        predicted_npv=1.0,
        actual_npv=0.0,
        ood_score=0.0,
        tau=1.0,
        surrogate_version=1,
        run_id="run-0001",
        canonical_schedule_hash="c" * 64,
    )

    with pytest.raises(VerificationError):
        check.relative_deviation


# --- 4. Переоценка последней версией и запрет заявлять число ---------------


def test_final_reevaluation_uses_the_latest_surrogate_version() -> None:
    """«Кандидат найден суррогатом версии r, а к концу цикла обучение ушло
    на r+1. Без переоценки цикл выбирает кандидата по модели, которой уже
    нет» — проверяется версией, а не фактом вызова."""

    first = _Surrogate(version=1, bias=1_000_000.0)
    second = _Surrogate(version=2, bias=1_000_000.0)
    third = _Surrogate(version=3, bias=0.0)
    retrainer = _Retrainer([second, third])

    report = _loop(
        surrogate=first,
        truth=_Truth(),
        retrain=retrainer,
        criterion=_tolerance(0.0),
        start_theta=_theta(),
        max_rounds=2,
    )

    assert report.final_surrogate_version == 3
    # Переоценка обязана быть сделана третьей версией: у неё нет смещения.
    assert third.calls, "последняя версия не вызывалась при переоценке"


def test_best_candidate_is_chosen_by_fact_not_by_prediction() -> None:
    """Все кандидаты таблицы прогнаны на OPM, истина по ним известна — брать
    лучшего по прогнозу значило бы доверять модели там, где есть замер."""

    report = _loop(
        surrogate=_Surrogate(),
        truth=_Truth(),
        retrain=_Retrainer([]),
        criterion=_tolerance(0.5),
        start_theta=_theta(),
        max_rounds=2,
    )

    assert report.best.actual_npv == max(check.actual_npv for check in report.table)


def test_self_consistent_is_false_when_the_latest_model_disagrees() -> None:
    """Несогласованный кандидат допустим как результат, но помечен (§6.5)."""

    first = _Surrogate(version=1, bias=1_000_000.0)
    disagreeing = _Surrogate(version=2, bias=5_000_000.0)
    retrainer = _Retrainer([disagreeing])

    report = _loop(
        surrogate=first,
        truth=_Truth(),
        retrain=retrainer,
        criterion=_tolerance(0.001),
        start_theta=_theta(),
        max_rounds=1,
    )

    assert report.self_consistent is False
    assert isinstance(report.reevaluation, SurrogateVerdict)


def test_self_consistent_is_true_when_the_latest_model_reproduces_the_choice() -> None:
    report = _loop(
        surrogate=_Surrogate(),
        truth=_Truth(),
        retrain=_Retrainer([]),
        criterion=_tolerance(0.5),
        start_theta=_theta(),
        max_rounds=2,
    )

    assert report.self_consistent is True


def test_report_carries_no_claimable_npv_field() -> None:
    """§10.5 и карточка Андрея: задача 39 — внутренний выбор кандидата, не
    сдача. Отсутствие поля с заявляемым числом здесь структурное, а не
    договорённость: перепутать два «финала» слишком легко."""

    names = {field.name for field in fields(VerificationReport)}
    forbidden = {
        "npv_methodology",
        "final_npv",
        "declared_npv",
        "submission_npv",
    }

    assert names & forbidden == set()


def test_module_never_builds_the_final_artifact() -> None:
    """Тот же запрет статически: цикл не импортирует и не собирает
    `FinalNpvArtifact` — это принадлежит задаче 62."""

    tree = ast.parse((ROOT / "verification.py").read_text(encoding="utf-8"))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            names.update(alias.asname or alias.name for alias in node.names)
        elif isinstance(node, ast.Name):
            names.add(node.id)

    assert "FinalNpvArtifact" not in names


# --- Отказы вместо правдоподобных чисел ------------------------------------


def test_zero_runs_per_round_is_rejected() -> None:
    with pytest.raises(VerificationError):
        _loop(
            surrogate=_Surrogate(),
            truth=_Truth(),
            retrain=_Retrainer([]),
            criterion=_tolerance(0.5),
            start_theta=_theta(),
            runs_per_round=0,
        )


def test_non_expanding_expansion_factor_is_rejected() -> None:
    with pytest.raises(VerificationError):
        _loop(
            surrogate=_Surrogate(),
            truth=_Truth(),
            retrain=_Retrainer([]),
            criterion=_tolerance(0.5),
            start_theta=_theta(),
            tau_expansion=1.0,
        )


def test_contraction_outside_the_unit_interval_is_rejected() -> None:
    for bad in (0.0, 1.0, 1.5):
        with pytest.raises(VerificationError):
            _loop(
                surrogate=_Surrogate(),
                truth=_Truth(),
                retrain=_Retrainer([]),
                criterion=_tolerance(0.5),
                start_theta=_theta(),
                tau_contraction=bad,
            )


def test_negative_ood_score_is_rejected() -> None:
    with pytest.raises(VerificationError):
        SurrogateVerdict(predicted_npv=1.0, ood_score=-0.1)


def test_truth_without_run_id_is_rejected() -> None:
    """Строка таблицы §10.3 без `run_id` ни с чем не связана."""

    with pytest.raises(VerificationError):
        TruthVerdict(npv=1.0, run_id="", canonical_schedule_hash="c" * 64)
