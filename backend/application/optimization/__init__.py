"""Граница θ → OptimizerResult и поиск, который её двигает.

Спецификация: docs/context/08_contracts.md §6.1, contracts/policy.py.

`interface` — сама граница (задача 37): единственное, что видит оптимизатор.
`search` — CMA-ES поверх неё (задача 38): выбор семейства обоснован в
докстринге модуля, и он обратим — `optimize` зависит только от
`ObjectiveFunction`.
"""

from __future__ import annotations

from .interface import (
    NominalObjective,
    Objective,
    ProvenanceSource,
    ScenarioEvaluator,
    ScenarioOutcome,
)
from .search import (
    Evaluation,
    ObjectiveFunction,
    OptimizerError,
    SearchReport,
    default_population,
    is_better,
    optimize,
)

__all__ = [
    "Evaluation",
    "NominalObjective",
    "Objective",
    "ObjectiveFunction",
    "OptimizerError",
    "ProvenanceSource",
    "ScenarioEvaluator",
    "ScenarioOutcome",
    "SearchReport",
    "default_population",
    "is_better",
    "optimize",
]
