"""RunArtifact — то, что читает интерфейс. README.md §9."""

from __future__ import annotations

from dataclasses import dataclass

from .connectivity import Groups, Lambda
from .constraints import Constraints
from .economics import NpvTable
from .policy import TraceEntry
from .response import IntervalResponse, StateAtDate
from .schedule import Schedule
from .simulation import FinalNpvArtifact


@dataclass(frozen=True, slots=True)
class RunArtifact:
    """Бандл, собираемый после прогона; интерфейс не вычисляет ничего и
    берёт всё отсюда. Демонстрация воспроизводит готовый артефакт, а не
    считает заново.

    final_npv не пустой только у одного артефакта в библиотеке — того,
    что прошёл финальную сдачу (docs/context/08_contracts.md §10.5). Это
    единственный способ отличить в интерфейсе реально сданный вариант от
    рядового «что если»: у остальных сценариев — None.
    """

    config_hash: str
    schedule: Schedule
    state_at_date: tuple[StateAtDate, ...]
    interval_response: tuple[IntervalResponse, ...]
    npv_table: NpvTable
    trace: tuple[TraceEntry, ...]
    groups: Groups
    lambda_: Lambda
    constraints: Constraints
    converged: bool
    self_consistent: bool
    final_npv: FinalNpvArtifact | None = None
