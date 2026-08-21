from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Protocol

from aios_backend.core.contracts import Schedule, hash_schedule


class Evaluator(Protocol):
    def __call__(self, schedule: Schedule) -> "Evaluation": ...


@dataclass(frozen=True, slots=True)
class Evaluation:
    npv: float
    state: object


Policy = Callable[[object], Schedule]


@dataclass(frozen=True, slots=True)
class Visited:
    iteration: int
    schedule: Schedule
    schedule_hash: str
    npv: float

    def __post_init__(self) -> None:
        if self.iteration < 0:
            raise ValueError(f"номер итерации {self.iteration} отрицателен")


@dataclass(frozen=True, slots=True)
class FixedPointResult:
    schedule: Schedule
    schedule_hash: str
    npv: float
    converged: bool
    self_consistent: bool
    iterations: int
    visited: tuple[Visited, ...]

    def __post_init__(self) -> None:
        if self.iterations < 0:
            raise ValueError(f"число итераций {self.iterations} отрицательно")
        if not self.visited:
            raise ValueError(
                "неподвижная точка без посещённых расписаний: выбирать не из чего"
            )
        if self.converged and not self.self_consistent:
            raise ValueError(
                "сошедшееся расписание обязано быть самосогласованным: "
                "хеши совпали, значит отклик снят с него самого"
            )

    def hashes(self) -> tuple[str, ...]:
        return tuple(entry.schedule_hash for entry in self.visited)

    def best_visited(self) -> Visited:
        return max(self.visited, key=lambda entry: (entry.npv, -entry.iteration))


def resolve(
    policy: Policy,
    evaluator: Evaluator,
    initial_state: object,
    iteration_cap: int,
) -> FixedPointResult:
    if iteration_cap <= 0:
        raise ValueError(
            f"потолок итераций {iteration_cap} не положителен: потолок "
            f"берётся из конфига, а не назначается на месте"
        )
    schedule = policy(initial_state)
    current_hash = hash_schedule(schedule)
    visited: list[Visited] = []
    for iteration in range(iteration_cap):
        evaluation = evaluator(schedule)
        visited.append(
            Visited(
                iteration=iteration,
                schedule=schedule,
                schedule_hash=current_hash,
                npv=evaluation.npv,
            )
        )
        proposed = policy(evaluation.state)
        proposed_hash = hash_schedule(proposed)
        if proposed_hash == current_hash:
            return FixedPointResult(
                schedule=schedule,
                schedule_hash=current_hash,
                npv=evaluation.npv,
                converged=True,
                self_consistent=True,
                iterations=iteration + 1,
                visited=tuple(visited),
            )
        schedule = proposed
        current_hash = proposed_hash
    return _reevaluated_best(policy, evaluator, tuple(visited), iteration_cap)


def _reevaluated_best(
    policy: Policy,
    evaluator: Evaluator,
    visited: tuple[Visited, ...],
    iterations: int,
) -> FixedPointResult:
    best = max(visited, key=lambda entry: (entry.npv, -entry.iteration))
    final = evaluator(best.schedule)
    reaction_hash = hash_schedule(policy(final.state))
    return FixedPointResult(
        schedule=best.schedule,
        schedule_hash=best.schedule_hash,
        npv=final.npv,
        converged=False,
        self_consistent=reaction_hash == best.schedule_hash,
        iterations=iterations,
        visited=visited,
    )
