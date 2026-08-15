"""Граница θ → OptimizerResult. Единственное, что видит оптимизатор.

Полная спецификация: docs/context/08_contracts.md §6.1, contracts/policy.py.
"""

from __future__ import annotations

from .interface import (
    NominalObjective,
    Objective,
    ProvenanceSource,
    ScenarioEvaluator,
    ScenarioOutcome,
)

__all__ = [
    "NominalObjective",
    "Objective",
    "ProvenanceSource",
    "ScenarioEvaluator",
    "ScenarioOutcome",
]
