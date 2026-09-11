
from __future__ import annotations

from backend.contexts.optimization.domain.errors import (
    OptimizerError,
)

import math
import random
from dataclasses import dataclass
from typing import Protocol, Sequence

from backend.core.contracts import OptimizerResult, Theta
from backend.contexts.policy.domain.policy import MAX_THETA_PARAMS

from backend.contexts.optimization.domain.linalg import (
    jacobi_eigen,
    matrix_vector,
    symmetrize,
    transpose_matrix_vector,
)


class ObjectiveFunction(Protocol):
    def __call__(self, theta: Theta) -> OptimizerResult: ...


@dataclass(frozen=True, slots=True)
class Evaluation:
    theta: Theta
    result: OptimizerResult


@dataclass(frozen=True, slots=True)
class SearchReport:
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
    if result.feasible:
        return (0.0, -result.objective, 0.0)
    worst = max((violation.regret for violation in result.violations_by_scenario), default=0.0)
    return (1.0, float(len(result.violations_by_scenario)), worst)


def is_better(left: OptimizerResult, right: OptimizerResult) -> bool:
    return _rank_key(left) < _rank_key(right)


@dataclass(frozen=True, slots=True)
class _Space:
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
    if 0.0 <= value <= 1.0:
        return value
    folded = math.fmod(abs(value), 2.0)
    return folded if folded <= 1.0 else 2.0 - folded


@dataclass(frozen=True, slots=True)
class _Weights:
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
        for member_index in range(population):
            if generation == 1 and member_index == 0:
                unit = tuple(mean)
            else:
                normal = [rng.gauss(0.0, 1.0) for _ in range(size)]
                scaled = [deviations[i] * normal[i] for i in range(size)]
                step = matrix_vector(basis, scaled)
                raw = [mean[i] + sigma * step[i] for i in range(size)]
                unit = tuple(_reflect(value) for value in raw)

            theta = space.to_theta(unit, start)
            evaluation = Evaluation(theta=theta, result=objective(theta))
            history.append(evaluation)

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

        rotated = transpose_matrix_vector(basis, mean_step)
        whitened_rotated = [rotated[i] / deviations[i] for i in range(size)]
        whitened = matrix_vector(basis, whitened_rotated)

        c_sigma_factor = math.sqrt(tuning.c_sigma * (2.0 - tuning.c_sigma) * tuning.mu_eff)
        path_sigma = [
            (1.0 - tuning.c_sigma) * path_sigma[i] + c_sigma_factor * whitened[i]
            for i in range(size)
        ]
        path_sigma_norm = math.sqrt(sum(value * value for value in path_sigma))

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
