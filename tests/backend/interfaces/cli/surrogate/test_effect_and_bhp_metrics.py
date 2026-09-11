from __future__ import annotations

import ast
import statistics
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import pytest

from backend.contexts.reservoir.domain.response import ActiveControlMode, StateAtDate
from backend.interfaces.cli.surrogate.tools import surrogate_metrics_report as _surrogate_metrics_report

REPORT_SOURCE = Path(_surrogate_metrics_report.__file__)

_EXTRACTED = (
    "_quantile",
    "_distribution",
    "_scaled_distribution",
    "_adjacent_pairs",
    "_effect_error",
    "_bhp_absolute_errors",
    "_bhp_channel",
)


def _module_ast(path: Path) -> ast.Module:
    return ast.parse(path.read_text(encoding="utf-8"))


def _assignment(module: ast.Module, name: str) -> ast.Assign:
    for node in module.body:
        if isinstance(node, ast.Assign) and any(
            isinstance(target, ast.Name) and target.id == name for target in node.targets
        ):
            return node
    raise AssertionError(f"constant {name} not found")


def _load_report_namespace() -> dict[str, Any]:
    module = _module_ast(REPORT_SOURCE)
    wanted = set(_EXTRACTED)
    body: list[ast.stmt] = [
        node
        for node in module.body
        if isinstance(node, ast.ClassDef) and node.name == "MetricsReportError"
    ]
    body.append(_assignment(module, "EFFECT_THRESHOLD_RUB"))
    body.extend(
        node
        for node in module.body
        if isinstance(node, ast.FunctionDef) and node.name in wanted
    )
    found = {node.name for node in body if isinstance(node, ast.FunctionDef)}
    assert found == wanted, f"the report is missing functions: {sorted(wanted - found)}"
    namespace: dict[str, Any] = {
        "statistics": statistics,
        "Sequence": Sequence,
        "StateAtDate": StateAtDate,
        "__annotations__": {},
    }
    exec(
        compile(ast.Module(body=body, type_ignores=[]), str(REPORT_SOURCE), "exec"),
        namespace,
    )
    return namespace


REPORT = _load_report_namespace()
MetricsReportError = REPORT["MetricsReportError"]
THRESHOLD = REPORT["EFFECT_THRESHOLD_RUB"]


def _state(well: str, index: int, bhp: float) -> StateAtDate:
    return StateAtDate(
        deck_date_index=index,
        well=well,
        liquid_rate=10.0,
        oil_rate=5.0,
        injection_rate=0.0,
        thp=20.0,
        bhp=bhp,
        well_efficiency=1.0,
        active_control_mode=ActiveControlMode.RATE_TARGET,
    )


def test_report_source_carries_no_comments_and_no_docstrings() -> None:
    text = REPORT_SOURCE.read_text(encoding="utf-8")
    module = _module_ast(REPORT_SOURCE)

    assert ast.get_docstring(module) is None
    for node in ast.walk(module):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            assert ast.get_docstring(node) is None, node.name
    for number, line in enumerate(text.split("\n"), start=1):
        stripped = line.strip()
        if not stripped.startswith("#"):
            continue
        assert stripped.startswith(("# type:", "# noqa", "# pragma")), f"line {number}"


def test_effect_error_matches_hand_computed_numbers() -> None:
    actual = [30.0e6, 20.0e6, 6.0e6]
    predicted = [30.0e6, 22.0e6, 12.0e6]

    effect = REPORT["_effect_error"](actual, predicted)

    assert effect["n_pairs"] == 2
    assert effect["n_significant_pairs"] == 2
    assert effect["n_degenerate_pairs"] == 0
    first, second = effect["rows"]
    assert first["true_delta_rub"] == pytest.approx(10.0e6)
    assert first["predicted_delta_rub"] == pytest.approx(8.0e6)
    assert first["absolute_error_rub"] == pytest.approx(2.0e6)
    assert first["relative_error_pct"] == pytest.approx(20.0)
    assert second["true_delta_rub"] == pytest.approx(14.0e6)
    assert second["predicted_delta_rub"] == pytest.approx(10.0e6)
    assert second["absolute_error_rub"] == pytest.approx(4.0e6)
    assert second["relative_error_pct"] == pytest.approx(4.0 / 14.0 * 100.0)
    assert effect["effect_error_pct_median"] == pytest.approx(
        (20.0 + 4.0 / 14.0 * 100.0) / 2.0
    )
    assert effect["effect_error_pct_max"] == pytest.approx(4.0 / 14.0 * 100.0)
    assert effect["absolute_error_mln_rub"]["median"] == pytest.approx(3.0)
    assert effect["sign_agreement"] == pytest.approx(1.0)


def test_pairs_are_adjacent_in_the_true_ranking_not_all_pairs() -> None:
    actual = [1.0e6, 40.0e6, 20.0e6, 60.0e6]

    pairs = REPORT["_adjacent_pairs"](actual)

    assert pairs == [(3, 1), (1, 2), (2, 0)]
    assert len(pairs) == len(actual) - 1


def test_near_zero_true_difference_is_reported_separately_not_as_infinity() -> None:
    actual = [10.0e6, 10.0e6 + 1.0, 4.0e6]
    predicted = [10.0e6, 10.0e6 - 500_000.0, 5.0e6]

    effect = REPORT["_effect_error"](actual, predicted)

    assert effect["n_pairs"] == 2
    assert effect["n_degenerate_pairs"] == 1
    assert effect["n_significant_pairs"] == 1
    degenerate = next(row for row in effect["rows"] if not row["significant"])
    assert degenerate["relative_error_pct"] is None
    assert degenerate["absolute_error_rub"] == pytest.approx(500_001.0)
    assert effect["degenerate_absolute_error_mln_rub"]["median"] == pytest.approx(
        0.500001
    )
    for value in (
        effect["effect_error_pct_median"],
        effect["effect_error_pct_p95"],
        effect["effect_error_pct_max"],
    ):
        assert value == value
        assert value not in (float("inf"), float("-inf"))


def test_all_pairs_degenerate_says_so_instead_of_printing_a_number() -> None:
    actual = [5.0e6, 5.0e6 + 10.0, 5.0e6 + 20.0]
    predicted = [5.0e6, 4.0e6, 6.0e6]

    effect = REPORT["_effect_error"](actual, predicted)

    assert effect["effect_error_pct_median"] is None
    assert effect["effect_error_pct_p95"] is None
    assert "relative_error_unavailable" in effect
    assert effect["n_degenerate_pairs"] == 2
    assert effect["absolute_error_mln_rub"]["n"] == 2.0


def test_threshold_is_a_million_roubles_and_must_be_positive() -> None:
    assert THRESHOLD == 1_000_000.0
    with pytest.raises(MetricsReportError):
        REPORT["_effect_error"]([2.0e6, 1.0e6], [2.0e6, 1.0e6], threshold_rub=0.0)


def test_single_scenario_and_empty_sample_raise_instead_of_returning_zero() -> None:
    with pytest.raises(MetricsReportError):
        REPORT["_effect_error"]([1.0e6], [1.0e6])
    with pytest.raises(MetricsReportError):
        REPORT["_effect_error"]([], [])
    with pytest.raises(MetricsReportError):
        REPORT["_distribution"]([], "check")
    with pytest.raises(MetricsReportError):
        REPORT["_bhp_channel"]([])


def test_mismatched_lengths_are_an_error() -> None:
    with pytest.raises(MetricsReportError):
        REPORT["_effect_error"]([1.0e6, 2.0e6, 3.0e6], [1.0e6, 2.0e6])


def test_median_and_p95_on_a_known_sample() -> None:
    values = [float(value) for value in range(1, 101)]

    distribution = REPORT["_distribution"](values, "check")

    assert distribution["n"] == 100.0
    assert distribution["median"] == pytest.approx(50.5)
    assert distribution["p95"] == pytest.approx(96.0)
    assert distribution["max"] == pytest.approx(100.0)
    assert REPORT["_quantile"](sorted(values), 0.95) == pytest.approx(96.0)


def test_p95_of_a_short_sample_stays_inside_the_sample() -> None:
    ordered = [1.0, 2.0, 3.0]

    assert REPORT["_quantile"](ordered, 0.95) == pytest.approx(3.0)
    assert REPORT["_quantile"]([7.0], 0.95) == pytest.approx(7.0)


def test_scaled_distribution_keeps_the_count_unscaled() -> None:
    scaled = REPORT["_scaled_distribution"]([2.0e6, 4.0e6, 6.0e6], "check", 1e6)

    assert scaled["n"] == 3.0
    assert scaled["median"] == pytest.approx(4.0)
    assert scaled["max"] == pytest.approx(6.0)


def test_bhp_channel_error_is_extracted_from_paired_states() -> None:
    predicted = [_state("P1", 0, 100.0), _state("P1", 1, 90.0), _state("P2", 0, 70.0)]
    actual = [_state("P1", 0, 104.0), _state("P1", 1, 89.0), _state("P2", 0, 80.0)]

    errors = REPORT["_bhp_absolute_errors"](predicted, actual)

    assert errors == pytest.approx([4.0, 1.0, 10.0])


def test_bhp_channel_reaches_the_artifact_with_median_and_p95() -> None:
    errors = [float(value) for value in range(1, 21)]

    channel = REPORT["_bhp_channel"]([("constrained-opm-a", errors)])

    assert channel["channel"] == "bhp"
    assert channel["unit"] == "bar"
    assert channel["n_states"] == 20
    assert channel["n_scenarios"] == 1
    assert channel["bhp_error_bar_median"] == pytest.approx(10.5)
    assert channel["bhp_error_bar_p95"] == pytest.approx(20.0)
    assert channel["bhp_error_bar_max"] == pytest.approx(20.0)
    assert channel["per_scenario"][0]["run"] == "constrained-opm-a"
    assert channel["per_scenario"][0]["n_states"] == 20


def test_bhp_channel_pools_scenarios() -> None:
    channel = REPORT["_bhp_channel"](
        [("run-a", [1.0, 3.0]), ("run-b", [5.0, 7.0])]
    )

    assert channel["n_states"] == 4
    assert channel["n_scenarios"] == 2
    assert channel["bhp_error_bar_median"] == pytest.approx(4.0)


def test_missing_fact_for_a_predicted_state_is_an_error() -> None:
    predicted = [_state("P1", 0, 100.0), _state("P2", 0, 70.0)]
    actual = [_state("P1", 0, 104.0)]

    with pytest.raises(MetricsReportError):
        REPORT["_bhp_absolute_errors"](predicted, actual)


def test_duplicated_fact_state_is_an_error() -> None:
    predicted = [_state("P1", 0, 100.0)]
    actual = [_state("P1", 0, 104.0), _state("P1", 0, 99.0)]

    with pytest.raises(MetricsReportError):
        REPORT["_bhp_absolute_errors"](predicted, actual)


def test_no_predicted_state_is_an_error_not_an_empty_zero() -> None:
    with pytest.raises(MetricsReportError):
        REPORT["_bhp_absolute_errors"]([], [_state("P1", 0, 104.0)])


def test_report_wires_effect_and_bhp_into_both_tables() -> None:
    module = _module_ast(REPORT_SOURCE)
    held_out = next(
        node
        for node in module.body
        if isinstance(node, ast.FunctionDef) and node.name == "_held_out"
    )
    manifold = next(
        node
        for node in module.body
        if isinstance(node, ast.FunctionDef) and node.name == "_manifold"
    )

    held_out_source = ast.unparse(held_out)
    manifold_source = ast.unparse(manifold)

    assert "_effect_error(actual" in held_out_source
    assert "'bhp_channel_unavailable'" in held_out_source
    assert "_effect_error(actual, predicted)" in manifold_source
    assert "_bhp_absolute_errors" in manifold_source
    assert "'bhp_channel'" in manifold_source
    assert "load_response_artifact" in manifold_source
