"""Оптимизатор θ — задача 38, docs/context/08_contracts.md §6.1.

Семейство выбрано: **CMA-ES**, эволюционная стратегия с адаптацией
ковариации. `07_concept.md` §8 п.2 оставлял три кандидата — эволюционные
методы, градиент по дифференцируемому суррогату и пошагово обученная
политика; два последних отпадают не по вкусу, а по входным данным:

- градиент требует дифференцируемого суррогата, а `RawModelOutput`
  (`surrogate/raw_model_output.py`) — это числа, не граф вычислений;
- пошагово обученная политика правит не θ, а сам вид правил — то есть
  меняет границу §6.1, а не способ двигаться внутри неё.

Остаётся эволюционная ветвь, и §6.1 называет в ней CMA-ES прямым текстом
(«Замена CMA-ES на градиент … не задевает ничего вокруг»). Выбор обратим
по построению: `optimize` зависит только от `ObjectiveFunction`, и другой
метод подставляется вместо неё, ничего вокруг не трогая.

**Почему именно CMA-ES, а не покоординатный спуск или сетка.** θ — не
больше десяти чисел (`MAX_THETA_PARAMS`), но каждая её оценка стоит
прогона: на реальном OPM это 513 с (`SURROGATE_HANDOFF.md` §2), на
суррогате — дешевле, но всё равно не бесплатно. Сетка по 10 измерениям
недопустима арифметически, покоординатный спуск слеп к взаимодействию
правил (R1 и R4 двигают одну и ту же уставку с разных сторон), а CMA-ES
выучивает именно ковариацию — то есть какие комбинации параметров ходят
вместе, — и делает это за десятки, а не тысячи оценок.

## Ограничение — не штраф, и здесь это не декларация

`OptimizerResult` не скаляр именно потому, что устойчивость сформулирована
как ограничение (§13.3). Оптимизатору всё равно нужно уметь сравнивать две
θ, и вот единственное место, где это сравнение определено, — `_rank_key`:

1. допустимая точка всегда лучше недопустимой, каким бы ни был `objective`;
2. две допустимые сравниваются по `objective`, и только по нему;
3. две недопустимые — по числу нарушенных сценариев, затем по худшему
   `regret`.

Пункт 3 нужен, чтобы поиск умел выбираться из недопустимой области, и он
не превращает ограничение в штраф: `objective` в него не входит вовсе, а
недопустимая точка не может обогнать допустимую ни при каком значении
`regret`. **Сложения по батарее здесь по-прежнему нет** — ни в целевой
функции, ни в ранжировании: `max`, а не `sum` (`optimizer/interface.py`,
«сложение здесь никогда не встречается»).

## Границы θ соблюдаются, а не штрафуются

Поиск идёт в единичном кубе: `bounds` из `Theta` отображают каждый
параметр в `[0, 1]`, выборка отражается от стенок куба. Поэтому ни одна
оценённая θ не выходит за объявленные границы — это свойство конструкции,
а не следствие удачной сходимости. Отражение выбрано вместо обрезки,
потому что обрезка сваливает целое облако точек ровно на границу и
ковариация вырождается.
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass
from typing import Protocol, Sequence

from contracts import OptimizerResult, Theta
from contracts.policy import MAX_THETA_PARAMS

from optimizer.linalg import jacobi_eigen, matrix_vector, symmetrize, transpose_matrix_vector


class OptimizerError(ValueError):
    """Поиск не может быть поставлен: вырожденные границы, пустая θ, нулевой бюджет."""


class ObjectiveFunction(Protocol):
    """Граница §6.1. `optimizer.Objective` ей удовлетворяет.

    Оптимизатор не знает, что стоит за вызовом — прогон OPM, суррогат или
    что-то ещё; он знает только, что вызов дорогой и что ответ не скаляр.
    """

    def __call__(self, theta: Theta) -> OptimizerResult: ...


@dataclass(frozen=True, slots=True)
class Evaluation:
    """Одна оценённая точка: θ и полный ответ границы §6.1."""

    theta: Theta
    result: OptimizerResult


@dataclass(frozen=True, slots=True)
class SearchReport:
    """Итог поиска.

    `history` хранится целиком и в порядке оценки: это и есть сдаваемая
    трасса выбора кандидата, из неё же собирается таблица «предсказано
    против факта» внешнего цикла верификации (§10.1).
    """

    best: Evaluation
    history: tuple[Evaluation, ...]
    generations: int
    stop_reason: str

    def __post_init__(self) -> None:
        if not self.history:
            raise OptimizerError("отчёт поиска без единой оценки")
        if self.generations < 1:
            raise OptimizerError(f"поколений {self.generations} < 1")

    @property
    def evaluations(self) -> int:
        return len(self.history)

    @property
    def feasible_found(self) -> bool:
        return self.best.result.feasible

    @property
    def feasible_history(self) -> tuple[Evaluation, ...]:
        return tuple(item for item in self.history if item.result.feasible)


def _rank_key(result: OptimizerResult) -> tuple[float, float, float]:
    """Ключ сравнения двух θ. Единственное место, где определено «лучше».

    Первая координата — допустимость: 0 у допустимой, 1 у недопустимой.
    Она доминирует над остальными, поэтому недопустимая точка не обгоняет
    допустимую ни при каком `objective` и ни при каком `regret`.
    """

    if result.feasible:
        return (0.0, -result.objective, 0.0)
    worst = max((violation.regret for violation in result.violations_by_scenario), default=0.0)
    return (1.0, float(len(result.violations_by_scenario)), worst)


def is_better(left: OptimizerResult, right: OptimizerResult) -> bool:
    """`left` строго лучше `right` по правилу выше."""

    return _rank_key(left) < _rank_key(right)


@dataclass(frozen=True, slots=True)
class _Space:
    """Отображение θ ↔ единичный куб. Порядок параметров — лексикографический
    по имени: словарь `Theta.values` порядка не гарантирует, а воспроизводимость
    при фиксированном seed требует одного и того же порядка координат."""

    names: tuple[str, ...]
    lower: tuple[float, ...]
    upper: tuple[float, ...]

    @classmethod
    def of(cls, theta: Theta) -> "_Space":
        names = tuple(sorted(theta.values))
        if not names:
            raise OptimizerError("θ без параметров: двигать нечего")
        if len(names) > MAX_THETA_PARAMS:
            raise OptimizerError(f"θ: {len(names)} параметров > {MAX_THETA_PARAMS}")
        lower: list[float] = []
        upper: list[float] = []
        for name in names:
            low, high = theta.bounds[name]
            if not math.isfinite(low) or not math.isfinite(high):
                raise OptimizerError(f"границы {name} не конечны: ({low}, {high})")
            if high <= low:
                raise OptimizerError(f"вырожденные границы {name}: ({low}, {high})")
            lower.append(float(low))
            upper.append(float(high))
        return cls(names=names, lower=tuple(lower), upper=tuple(upper))

    @property
    def size(self) -> int:
        return len(self.names)

    def to_unit(self, theta: Theta) -> tuple[float, ...]:
        return tuple(
            (theta.values[name] - self.lower[i]) / (self.upper[i] - self.lower[i])
            for i, name in enumerate(self.names)
        )

    def to_theta(self, unit: Sequence[float], template: Theta) -> Theta:
        values = dict(template.values)
        for i, name in enumerate(self.names):
            values[name] = self.lower[i] + unit[i] * (self.upper[i] - self.lower[i])
        return Theta(values=values, bounds=dict(template.bounds))


def _reflect(value: float) -> float:
    """Отражение в `[0, 1]` от обеих стенок, сколько бы раз ни потребовалось.

    Треугольная волна периода 2: значение вне куба зеркалится обратно,
    далёкий выброс не прилипает к границе, а попадает внутрь.
    """

    if 0.0 <= value <= 1.0:
        return value
    folded = math.fmod(abs(value), 2.0)
    return folded if folded <= 1.0 else 2.0 - folded


@dataclass(frozen=True, slots=True)
class _Weights:
    """Веса рекомбинации и коэффициенты адаптации CMA-ES (Hansen, стандартный
    набор). Выведены из размерности и размера популяции, свободных ручек нет —
    это существенно: подбирать их под задачу означало бы подгонять оптимизатор
    под конкретный отклик и терять переносимость на сценарии батареи."""

    weights: tuple[float, ...]
    mu: int
    mu_eff: float
    c_c: float
    c_sigma: float
    c_1: float
    c_mu: float
    d_sigma: float
    chi_n: float

    @classmethod
    def of(cls, size: int, population: int) -> "_Weights":
        mu = population // 2
        raw = [math.log(mu + 0.5) - math.log(i + 1) for i in range(mu)]
        total = sum(raw)
        weights = tuple(value / total for value in raw)
        mu_eff = 1.0 / sum(value * value for value in weights)

        c_c = (4.0 + mu_eff / size) / (size + 4.0 + 2.0 * mu_eff / size)
        c_sigma = (mu_eff + 2.0) / (size + mu_eff + 5.0)
        c_1 = 2.0 / ((size + 1.3) ** 2 + mu_eff)
        c_mu = min(
            1.0 - c_1,
            2.0 * (mu_eff - 2.0 + 1.0 / mu_eff) / ((size + 2.0) ** 2 + mu_eff),
        )
        d_sigma = (
            1.0 + 2.0 * max(0.0, math.sqrt((mu_eff - 1.0) / (size + 1.0)) - 1.0) + c_sigma
        )
        chi_n = math.sqrt(size) * (1.0 - 1.0 / (4.0 * size) + 1.0 / (21.0 * size * size))
        return cls(
            weights=weights,
            mu=mu,
            mu_eff=mu_eff,
            c_c=c_c,
            c_sigma=c_sigma,
            c_1=c_1,
            c_mu=c_mu,
            d_sigma=d_sigma,
            chi_n=chi_n,
        )


def default_population(size: int) -> int:
    """λ по правилу Хансена: 4 + ⌊3·ln n⌋, но не меньше четырёх — при
    меньшей популяции μ = λ/2 вырождается и рекомбинация теряет смысл."""

    return max(4, 4 + int(math.floor(3.0 * math.log(size))))


def optimize(
    objective: ObjectiveFunction,
    start: Theta,
    *,
    seed: int,
    max_evaluations: int,
    population: int | None = None,
    initial_sigma: float = 0.3,
    sigma_tolerance: float = 1e-8,
    stall_generations: int = 20,
) -> SearchReport:
    """Двигает θ, максимизируя `objective` при ограничении `feasible`.

    `seed` берётся из конфига (`config.schema.seed_for(config, "optimizer")`),
    а не назначается на месте: сдача требует воспроизводимости без
    неконтролируемых случайных параметров.

    `max_evaluations` — бюджет вызовов границы, и он жёсткий: считается
    именно оценками, а не поколениями, потому что дорого стоит вызов, а не
    итерация. Последнее поколение оценивается целиком либо не начинается.

    `initial_sigma` — доля единичного куба, 0.3 покрывает объявленные
    границы примерно на треть в каждую сторону от старта.
    """

    if max_evaluations < 1:
        raise OptimizerError(f"бюджет оценок {max_evaluations} < 1")

    space = _Space.of(start)
    size = space.size
    population = default_population(size) if population is None else population
    if population < 4:
        raise OptimizerError(f"популяция {population} < 4")
    if not 0.0 < initial_sigma:
        raise OptimizerError(f"начальный шаг {initial_sigma} не положителен")

    tuning = _Weights.of(size, population)
    rng = random.Random(seed)

    mean = list(space.to_unit(start))
    sigma = float(initial_sigma)
    covariance = [[1.0 if i == j else 0.0 for j in range(size)] for i in range(size)]
    path_sigma = [0.0] * size
    path_c = [0.0] * size

    history: list[Evaluation] = []
    best: Evaluation | None = None
    best_generation = 0
    generation = 0
    stop_reason = "бюджет оценок исчерпан"

    while len(history) < max_evaluations:
        if max_evaluations - len(history) < population:
            stop_reason = "бюджета не хватает на целое поколение"
            break

        generation += 1
        eigenvalues, basis = jacobi_eigen(symmetrize(covariance))
        if min(eigenvalues) <= 0.0:
            stop_reason = "ковариация потеряла положительную определённость"
            break
        deviations = [math.sqrt(value) for value in eigenvalues]

        offspring: list[tuple[tuple[float, ...], tuple[float, ...], Evaluation]] = []
        for _ in range(population):
            normal = [rng.gauss(0.0, 1.0) for _ in range(size)]
            scaled = [deviations[i] * normal[i] for i in range(size)]
            step = matrix_vector(basis, scaled)
            raw = [mean[i] + sigma * step[i] for i in range(size)]
            unit = tuple(_reflect(value) for value in raw)

            theta = space.to_theta(unit, start)
            evaluation = Evaluation(theta=theta, result=objective(theta))
            history.append(evaluation)

            # Шаг пересчитывается из отражённой точки, а не из сырой:
            # адаптация обязана видеть ту θ, которую действительно оценили.
            repaired_step = tuple((unit[i] - mean[i]) / sigma for i in range(size))
            offspring.append((unit, repaired_step, evaluation))

            if best is None or is_better(evaluation.result, best.result):
                best = evaluation
                best_generation = generation

        offspring.sort(key=lambda item: _rank_key(item[2].result))
        selected = offspring[: tuning.mu]

        old_mean = list(mean)
        mean = [
            sum(tuning.weights[k] * selected[k][0][i] for k in range(tuning.mu))
            for i in range(size)
        ]
        mean_step = [
            sum(tuning.weights[k] * selected[k][1][i] for k in range(tuning.mu))
            for i in range(size)
        ]

        # p_σ живёт в координатах C^{-1/2}: масштаб по каждой собственной оси
        # снимается, иначе длина пути мерила бы форму облака, а не смещение.
        rotated = transpose_matrix_vector(basis, mean_step)
        whitened_rotated = [rotated[i] / deviations[i] for i in range(size)]
        whitened = matrix_vector(basis, whitened_rotated)

        c_sigma_factor = math.sqrt(tuning.c_sigma * (2.0 - tuning.c_sigma) * tuning.mu_eff)
        path_sigma = [
            (1.0 - tuning.c_sigma) * path_sigma[i] + c_sigma_factor * whitened[i]
            for i in range(size)
        ]
        path_sigma_norm = math.sqrt(sum(value * value for value in path_sigma))

        # Отсечка Хансена: пока путь длиннее ожидаемого, p_c не накапливается,
        # иначе rank-one обновление разгоняет ковариацию вдоль случайного сноса.
        expected = tuning.chi_n * math.sqrt(
            1.0 - (1.0 - tuning.c_sigma) ** (2.0 * generation)
        )
        heaviside = 1.0 if path_sigma_norm / max(expected, 1e-300) < 1.4 + 2.0 / (size + 1.0) else 0.0
        c_c_factor = math.sqrt(tuning.c_c * (2.0 - tuning.c_c) * tuning.mu_eff)
        path_c = [
            (1.0 - tuning.c_c) * path_c[i] + heaviside * c_c_factor * mean_step[i]
            for i in range(size)
        ]

        correction = (1.0 - heaviside) * tuning.c_c * (2.0 - tuning.c_c)
        updated: list[list[float]] = []
        for i in range(size):
            row: list[float] = []
            for j in range(size):
                rank_one = path_c[i] * path_c[j]
                rank_mu = sum(
                    tuning.weights[k] * selected[k][1][i] * selected[k][1][j]
                    for k in range(tuning.mu)
                )
                value = (
                    (1.0 - tuning.c_1 - tuning.c_mu) * covariance[i][j]
                    + tuning.c_1 * (rank_one + correction * covariance[i][j])
                    + tuning.c_mu * rank_mu
                )
                row.append(value)
            updated.append(row)
        covariance = symmetrize(updated)

        sigma *= math.exp(
            (tuning.c_sigma / tuning.d_sigma) * (path_sigma_norm / tuning.chi_n - 1.0)
        )
        if not math.isfinite(sigma) or sigma <= sigma_tolerance:
            stop_reason = "шаг σ ниже допуска: поиск сошёлся"
            break
        if generation - best_generation >= stall_generations:
            stop_reason = f"нет улучшения {stall_generations} поколений подряд"
            break
        if all(abs(mean[i] - old_mean[i]) <= sigma_tolerance for i in range(size)):
            stop_reason = "среднее перестало двигаться"
            break

    if best is None:
        raise OptimizerError(
            f"бюджет {max_evaluations} меньше одного поколения из {population} оценок: "
            f"ни одна θ не была оценена"
        )

    return SearchReport(
        best=best,
        history=tuple(history),
        generations=generation,
        stop_reason=stop_reason,
    )
