from __future__ import annotations

from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Callable, Mapping, Protocol

from backend.contexts.schedule.domain.schedule import Schedule
from backend.shared.hashing import hash_schedule

_EMPTY_FLOATS: Mapping[str, float] = MappingProxyType({})
_EMPTY_COUNTS: Mapping[str, int] = MappingProxyType({})


class Evaluator(Protocol):
    def __call__(self, schedule: Schedule) -> "Evaluation": ...


@dataclass(frozen=True, slots=True)
class Evaluation:
    npv: float
    state: object
    ood_score: float | None = None
    npv_parts: Mapping[str, float] = field(default=_EMPTY_FLOATS)
    sigma: float | None = None
    physics: Mapping[str, int] = field(default=_EMPTY_COUNTS)
    ood_worst: str | None = None


Policy = Callable[[object], Schedule]


@dataclass(frozen=True, slots=True)
class Visited:
    iteration: int
    schedule: Schedule
    schedule_hash: str
    npv: float
    ood_score: float | None = None
    npv_parts: Mapping[str, float] = field(default=_EMPTY_FLOATS)
    sigma: float | None = None
    physics: Mapping[str, int] = field(default=_EMPTY_COUNTS)
    ood_worst: str | None = None
    reaction_hash: str | None = None

    def __post_init__(self) -> None:
        if self.iteration < 0:
            raise ValueError(f"iteration number {self.iteration} is negative")

    def is_quiet(self) -> bool:
        if self.reaction_hash is None:
            raise ValueError(
                f"iteration {self.iteration}: the policy response was not recorded, so "
                f"there is nothing to judge whether the rules changed the schedule by"
            )
        return self.reaction_hash == self.schedule_hash


@dataclass(frozen=True, slots=True)
class FixedPointResult:
    schedule: Schedule
    schedule_hash: str
    npv: float
    converged: bool
    self_consistent: bool
    iterations: int
    visited: tuple[Visited, ...]
    ood_score: float | None = None
    npv_parts: Mapping[str, float] = field(default=_EMPTY_FLOATS)
    sigma: float | None = None
    physics: Mapping[str, int] = field(default=_EMPTY_COUNTS)
    ood_worst: str | None = None

    def __post_init__(self) -> None:
        if self.iterations < 0:
            raise ValueError(f"the iteration count {self.iterations} is negative")
        if not self.visited:
            raise ValueError(
                "a fixed point with no visited schedules: there is nothing to choose from"
            )
        if self.converged and not self.self_consistent:
            raise ValueError(
                "a converged schedule must be self-consistent: "
                "the hashes matched, so the response was taken off that very schedule"
            )

    def hashes(self) -> tuple[str, ...]:
        return tuple(entry.schedule_hash for entry in self.visited)

    def best_visited(self) -> Visited:
        return max(self.visited, key=lambda entry: (entry.npv, -entry.iteration))

    def quiet_steps(self) -> int:
        silent = [
            entry.iteration
            for entry in self.visited
            if entry.reaction_hash is None
        ]
        if silent:
            raise ValueError(
                f"iterations {silent} carry no recorded policy response: there is nothing "
                f"to compute the share of unchanged steps from"
            )
        return sum(1 for entry in self.visited if entry.is_quiet())

    def quiet_step_fraction(self) -> float:
        return self.quiet_steps() / len(self.visited)

    def as_equilibrium(self) -> "PolicyEquilibrium":
        return PolicyEquilibrium(
            iterations=self.iterations,
            converged=self.converged,
            self_consistent=self.self_consistent,
            quiet_steps=self.quiet_steps(),
            observed_steps=len(self.visited),
        )


@dataclass(frozen=True, slots=True)
class PolicyEquilibrium:
    iterations: int
    converged: bool
    self_consistent: bool
    quiet_steps: int
    observed_steps: int

    def __post_init__(self) -> None:
        if self.observed_steps <= 0:
            raise ValueError(
                "a policy equilibrium without a single observed step: the share "
                "of unchanged steps is undefined"
            )
        if not (0 <= self.quiet_steps <= self.observed_steps):
            raise ValueError(
                f"{self.quiet_steps} unchanged steps out of "
                f"{self.observed_steps}: the share is outside 0…1"
            )
        if self.iterations < 0:
            raise ValueError(f"the iteration count {self.iterations} is negative")
        if self.converged and not self.self_consistent:
            raise ValueError(
                "a converged policy must be self-consistent"
            )

    def quiet_step_fraction(self) -> float:
        return self.quiet_steps / self.observed_steps

    def settled(self) -> bool:
        return self.converged and self.self_consistent

    def as_dict(self) -> dict[str, object]:
        return {
            "iterations": self.iterations,
            "converged": self.converged,
            "self_consistent": self.self_consistent,
            "quiet_steps": self.quiet_steps,
            "observed_steps": self.observed_steps,
            "quiet_step_fraction": self.quiet_step_fraction(),
            "settled": self.settled(),
        }


def resolve(
    policy: Policy,
    evaluator: Evaluator,
    initial_state: object,
    iteration_cap: int,
) -> FixedPointResult:
    if iteration_cap <= 0:
        raise ValueError(
            f"the iteration cap {iteration_cap} is not positive: the cap "
            f"is taken from the config and not assigned on the spot"
        )
    schedule = policy(initial_state)
    current_hash = hash_schedule(schedule)
    visited: list[Visited] = []
    seen_hashes = {current_hash}
    for iteration in range(iteration_cap):
        evaluation = evaluator(schedule)
        proposed = policy(evaluation.state)
        proposed_hash = hash_schedule(proposed)
        visited.append(
            Visited(
                iteration=iteration,
                schedule=schedule,
                schedule_hash=current_hash,
                npv=evaluation.npv,
                ood_score=evaluation.ood_score,
                npv_parts=evaluation.npv_parts,
                sigma=evaluation.sigma,
                physics=evaluation.physics,
                ood_worst=evaluation.ood_worst,
                reaction_hash=proposed_hash,
            )
        )
        if proposed_hash == current_hash:
            return FixedPointResult(
                schedule=schedule,
                schedule_hash=current_hash,
                npv=evaluation.npv,
                converged=True,
                self_consistent=True,
                iterations=iteration + 1,
                visited=tuple(visited),
                ood_score=evaluation.ood_score,
                npv_parts=evaluation.npv_parts,
                sigma=evaluation.sigma,
                physics=evaluation.physics,
                ood_worst=evaluation.ood_worst,
            )
        if proposed_hash in seen_hashes:
            return _reevaluated_best(
                policy, evaluator, tuple(visited), iteration + 1
            )
        schedule = proposed
        current_hash = proposed_hash
        seen_hashes.add(current_hash)
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
        ood_score=final.ood_score,
        npv_parts=final.npv_parts,
        sigma=final.sigma,
        physics=final.physics,
        ood_worst=final.ood_worst,
    )
