"""Критерий «прогноз сошёлся» — задача 40, §10.4.

Карточка Андрея: «**замеряется на данных, а не выбирается**».

§10.4 оставляет вопрос открытым дословно: «Чем измерять "прогноз сошёлся":
абсолютное отклонение ЧДД, ранговая согласованность top-k или оба порога
сразу. **Не замерено.** [гипотеза]». Поэтому этот модуль не объявляет
победителя — он строит все три кандидата, прогоняет их по настоящей
таблице цикла верификации и меряет, какой из них ошибается реже и как
именно. Выбор делается числом, а не здесь.

## Что вообще значит «сошёлся»

Критерий стоит в цикле не сам по себе: по нему принимается ровно одно
решение — расширять область доверия или сжимать её (§10.1). Значит и
проверять его надо на этом решении, а не на «похожести чисел».

Истина раунда, с которой сравнивается критерий, такова: **был ли прав тот,
кто доверился суррогату**. Кандидат, которого суррогат поставил первым,
прогнан на OPM вместе с остальными — известно, насколько он на самом деле
хуже лучшего в раунде. Если эта просадка укладывается в допуск, доверие
было оправдано; если нет — расширять область было бы ошибкой.

## Две ошибки, и они не равноценны

- **Ложное расширение** — критерий сказал «сошлось», а доверие не было
  оправдано. Область растёт туда, где суррогат вводит в заблуждение, и
  следующие раунды тратят прогоны в этой зоне.
- **Упущенное расширение** — критерий сказал «разошлось», хотя доверие было
  оправдано. Цена — лишний раунд дообучения и сжатая область.

Складывать их в одну accuracy нельзя: первая ошибка уводит цикл, вторая
только замедляет. Поэтому кандидаты сравниваются лексикографически —
сначала по числу ложных расширений, потом по числу верных, — и ни одного
взвешенного суммирования здесь нет.

## Порог не назначается, а просматривается целиком

Каждый кандидат меряется на сетке порогов, и в отчёт идёт вся сетка.
Единственное число «оптимальный порог 0.07» скрывает, устойчив он или
стоит на игле: соседние пороги могут давать вдвое больше ложных
расширений. Человек, читающий отчёт, обязан видеть форму, а не точку.

## Замер на синтетике не считается

Правило 4 репозитория. `CalibrationReport.verdict` отказывается называть
победителя, если ему сказали, что таблица синтетическая: критерий,
откалиброванный на выдуманных данных, — это выбор, замаскированный под
замер, ровно то, что карточка запрещает.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from bridge.verification import CandidateCheck, RoundReport
from surrogate.crm import spearman


class ConvergenceError(ValueError):
    """Критерий нельзя замерить: пустая история, вырожденная сетка порогов."""


# --- Три кандидата §10.4 ----------------------------------------------------


def absolute_deviation_criterion(tolerance: float):
    """«Абсолютное отклонение ЧДД»: относительная ошибка каждого кандидата
    раунда не больше `tolerance`.

    Относительная, а не абсолютная в рублях: ЧДД Model_Z — величина порядка
    1e10 (`docs`: базовый сценарий 11886 млн), и порог в рублях пришлось бы
    переназначать при каждой смене нормативов.
    """

    if tolerance < 0.0:
        raise ConvergenceError(f"допуск {tolerance} отрицателен")

    def criterion(checks: Sequence[CandidateCheck]) -> bool:
        if not checks:
            raise ConvergenceError("критерий на пустом раунде не определён")
        return all(abs(check.relative_deviation) <= tolerance for check in checks)

    return criterion


def rank_agreement_criterion(minimum: float):
    """«Ранговая согласованность top-k»: корреляция Спирмена предсказанного
    и фактического ЧДД внутри раунда не ниже `minimum`.

    Это то, что цикл на самом деле использует: он берёт top-k по прогнозу,
    и важно, чтобы порядок внутри раунда был верен, а не чтобы числа
    совпали (§5.2 — сдаваемая метрика ранговая, не MAE).
    """

    if not -1.0 <= minimum <= 1.0:
        raise ConvergenceError(f"порог корреляции {minimum} вне [-1, 1]")

    def criterion(checks: Sequence[CandidateCheck]) -> bool:
        if not checks:
            raise ConvergenceError("критерий на пустом раунде не определён")
        if len(checks) < 2:
            # Ранговая согласованность одного кандидата не определена;
            # возвращать True значило бы объявлять сходимость даром.
            raise ConvergenceError(
                "ранговая согласованность требует минимум двух кандидатов в раунде"
            )
        predicted = [check.predicted_npv for check in checks]
        actual = [check.actual_npv for check in checks]
        return spearman(actual, predicted) >= minimum

    return criterion


def both_criterion(tolerance: float, minimum: float):
    """«Оба порога сразу» — конъюнкция, а не среднее.

    Среднее двух критериев позволило бы отличной корреляции выкупить
    провальное отклонение; конъюнкция — нет.
    """

    left = absolute_deviation_criterion(tolerance)
    right = rank_agreement_criterion(minimum)

    def criterion(checks: Sequence[CandidateCheck]) -> bool:
        return left(checks) and right(checks)

    return criterion


# --- Истина раунда ----------------------------------------------------------


def trust_was_justified(checks: Sequence[CandidateCheck], *, regret_tolerance: float) -> bool:
    """Был ли прав тот, кто доверился суррогату в этом раунде.

    Кандидат, поставленный суррогатом первым, сравнивается по **факту** с
    лучшим фактическим в раунде. Просадка в пределах допуска — доверие
    оправдано.
    """

    if not checks:
        raise ConvergenceError("истина на пустом раунде не определена")
    if regret_tolerance < 0.0:
        raise ConvergenceError(f"допуск просадки {regret_tolerance} отрицателен")

    predicted_best = max(checks, key=lambda check: check.predicted_npv)
    actual_best = max(check.actual_npv for check in checks)
    if actual_best == 0.0:
        raise ConvergenceError("лучший фактический ЧДД равен нулю: просадка не определена")

    shortfall = (actual_best - predicted_best.actual_npv) / abs(actual_best)
    return shortfall <= regret_tolerance


# --- Замер ------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class CriterionMeasurement:
    """Как один кандидат с одним порогом ведёт себя на настоящей истории."""

    name: str
    threshold: float
    n_rounds: int
    false_expansions: int
    missed_expansions: int
    correct_expansions: int
    correct_contractions: int

    @property
    def agreements(self) -> int:
        return self.correct_expansions + self.correct_contractions

    @property
    def agreement_rate(self) -> float:
        return self.agreements / self.n_rounds if self.n_rounds else 0.0

    @property
    def rank_key(self) -> tuple[int, int, float]:
        """Лексикографическое сравнение: сначала меньше ложных расширений,
        потом больше верных, потом — как разрыв связок — больше согласий.

        Взвешенной суммы здесь нет намеренно: вес означал бы курс обмена
        между «увели цикл» и «потратили раунд», а его никто не замерял.
        """

        return (self.false_expansions, -self.correct_expansions, -self.agreement_rate)


@dataclass(frozen=True, slots=True)
class CriterionSweep:
    """Весь просмотр порогов одного кандидата — форма, а не точка."""

    name: str
    measurements: tuple[CriterionMeasurement, ...]

    def __post_init__(self) -> None:
        if not self.measurements:
            raise ConvergenceError(f"{self.name}: пустая сетка порогов")

    @property
    def best(self) -> CriterionMeasurement:
        return min(self.measurements, key=lambda item: item.rank_key)

    @property
    def stable(self) -> bool:
        """Устойчив ли лучший порог: соседи по сетке не хуже вдвое по числу
        ложных расширений. Порог, стоящий на игле, доверия не заслуживает."""

        ordered = sorted(self.measurements, key=lambda item: item.threshold)
        index = ordered.index(self.best)
        neighbours = [
            ordered[i]
            for i in (index - 1, index + 1)
            if 0 <= i < len(ordered)
        ]
        if not neighbours:
            return False
        limit = max(1, 2 * self.best.false_expansions)
        return all(item.false_expansions <= limit for item in neighbours)


@dataclass(frozen=True, slots=True)
class CalibrationReport:
    """Итог замера: все кандидаты, их сетки и вердикт.

    `synthetic_inputs` обязателен к учёту: критерий, откалиброванный на
    выдуманных данных, — это выбор, замаскированный под замер.
    """

    sweeps: tuple[CriterionSweep, ...]
    n_rounds: int
    regret_tolerance: float
    synthetic_inputs: bool

    def sweep_of(self, name: str) -> CriterionSweep:
        for sweep in self.sweeps:
            if sweep.name == name:
                return sweep
        raise ConvergenceError(f"кандидата {name!r} нет в отчёте")

    @property
    def winner(self) -> CriterionMeasurement | None:
        """Лучший кандидат по всем сеткам, либо `None`, если вердикт не
        выносится (синтетика или слишком мало раундов)."""

        if self.synthetic_inputs or self.n_rounds < 2:
            return None
        return min(
            (sweep.best for sweep in self.sweeps), key=lambda item: item.rank_key
        )

    @property
    def verdict(self) -> str:
        if self.synthetic_inputs:
            return (
                "таблица помечена синтетической: критерий, откалиброванный на "
                "выдуманных данных, — это выбор, замаскированный под замер "
                "(правило 4), вердикт не выносится"
            )
        if self.n_rounds < 2:
            return (
                f"раундов {self.n_rounds}: на одном раунде критерий не "
                f"различается, замер не состоялся"
            )
        best = self.winner
        assert best is not None
        return (
            f"{best.name} с порогом {best.threshold:g}: ложных расширений "
            f"{best.false_expansions}, верных {best.correct_expansions} "
            f"из {self.n_rounds} раундов"
        )


def measure_criteria(
    rounds: Sequence[RoundReport],
    *,
    regret_tolerance: float,
    deviation_thresholds: Sequence[float] = (0.01, 0.02, 0.05, 0.10, 0.20),
    rank_thresholds: Sequence[float] = (0.0, 0.3, 0.5, 0.7, 0.9),
    synthetic_inputs: bool = False,
) -> CalibrationReport:
    """Замерить все три кандидата §10.4 на истории цикла верификации.

    Вход — раунды, а не отдельные строки: критерий принимает решение о
    раунде целиком, и мерить его надо на той же гранулярности.
    """

    if not rounds:
        raise ConvergenceError("замер на пустой истории цикла невозможен")
    if not deviation_thresholds or not rank_thresholds:
        raise ConvergenceError("пустая сетка порогов ничего не меряет")

    truth = [
        trust_was_justified(report.checks, regret_tolerance=regret_tolerance)
        for report in rounds
    ]

    def measure(name: str, threshold: float, criterion) -> CriterionMeasurement:
        false_expansions = 0
        missed_expansions = 0
        correct_expansions = 0
        correct_contractions = 0
        for report, justified in zip(rounds, truth):
            said_converged = criterion(report.checks)
            if said_converged and justified:
                correct_expansions += 1
            elif said_converged and not justified:
                false_expansions += 1
            elif justified:
                missed_expansions += 1
            else:
                correct_contractions += 1
        return CriterionMeasurement(
            name=name,
            threshold=threshold,
            n_rounds=len(rounds),
            false_expansions=false_expansions,
            missed_expansions=missed_expansions,
            correct_expansions=correct_expansions,
            correct_contractions=correct_contractions,
        )

    deviation = CriterionSweep(
        name="absolute_deviation",
        measurements=tuple(
            measure("absolute_deviation", t, absolute_deviation_criterion(t))
            for t in deviation_thresholds
        ),
    )
    rank = CriterionSweep(
        name="rank_agreement",
        measurements=tuple(
            measure("rank_agreement", t, rank_agreement_criterion(t))
            for t in rank_thresholds
        ),
    )
    # «Оба порога сразу» просматривается по своей сетке отклонения при
    # ранговом пороге, лучшем в одиночном замере: полный двумерный перебор
    # дал бы сетку, которую человек уже не прочитает глазами.
    best_rank = rank.best.threshold
    combined = CriterionSweep(
        name="both",
        measurements=tuple(
            measure("both", t, both_criterion(t, best_rank))
            for t in deviation_thresholds
        ),
    )

    return CalibrationReport(
        sweeps=(deviation, rank, combined),
        n_rounds=len(rounds),
        regret_tolerance=regret_tolerance,
        synthetic_inputs=synthetic_inputs,
    )
