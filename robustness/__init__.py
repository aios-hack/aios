"""Compatibility package. New code lives in :mod:`aios_backend.domain.robustness`."""

import sys

from aios_backend.application.optimization import scenario_baseline as _scenario_baseline
from aios_backend.domain import robustness as _implementation
from aios_backend.domain.robustness import *

BaselineSearch = _scenario_baseline.BaselineSearch
ObjectiveFactory = _scenario_baseline.ObjectiveFactory
RegretComputation = _scenario_baseline.RegretComputation
ScenarioBaselineError = _scenario_baseline.ScenarioBaselineError
compute_regret = _scenario_baseline.compute_regret
evaluation_budget = _scenario_baseline.evaluation_budget
scenario_baseline = _scenario_baseline.scenario_baseline
scenario_seed = _scenario_baseline.scenario_seed
worst_scenarios = _scenario_baseline.worst_scenarios

__all__ = _implementation.__all__ + [
    "BaselineSearch",
    "ObjectiveFactory",
    "RegretComputation",
    "ScenarioBaselineError",
    "compute_regret",
    "evaluation_budget",
    "scenario_baseline",
    "scenario_seed",
    "worst_scenarios",
]
__path__ = _implementation.__path__
sys.modules[__name__ + ".scenario_baseline"] = _scenario_baseline
