from __future__ import annotations

import hashlib
import statistics
import sys
from collections.abc import Sequence
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import torch
from backend.contexts.surrogate.application.model import _legacy_checkpoint_modules

from backend.contexts.economics.application.base_case import load_response_artifact
from backend.contexts.reservoir.domain.response import StateAtDate
from backend.contexts.showcase.infrastructure.artifact_io import _load_schedule
from backend.contexts.simulation.domain.perturbation_design import (
    build_plan,
    materialize,
)
from backend.contexts.surrogate.application.pipeline import PILOT_CONFIG, EXTRA_CONFIG
from backend.interfaces.cli.surrogate.tools.surrogate_metrics_errors import (
    MetricsReportError as _MetricsReportError,
)
from backend.interfaces.cli.surrogate.tools.surrogate_metrics_holdout import (
    DEFAULT_HOLDOUT,
    HOLDOUT_FORMAT,
    FrozenHoldout,
    FrozenHoldoutError,
    assert_holdout_excluded,
    load_frozen_holdout,
)
from backend.interfaces.cli.surrogate.tools.surrogate_metrics_scoring import (
    _component_metrics,
    _predict_response,
    _ranking,
    _regression,
    _score_schedule,
)
from backend.shared.hashing import hash_schedule
from backend.shared.json_io import read_json

EFFECT_THRESHOLD_RUB = 1_000_000.0


class MetricsReportError(RuntimeError):
    pass


MetricsReportError = _MetricsReportError


def _quantile(ordered: list[float], share: float) -> float:
    if not ordered:
        raise MetricsReportError(
            "the quantile of an empty sample is undefined; a zero in place of a number is forbidden"
        )
    return ordered[min(len(ordered) - 1, int(share * len(ordered)))]


def _distribution(values: list[float], what: str) -> dict[str, float]:
    if not values:
        raise MetricsReportError(
            f"{what}: the sample is empty, the distribution is not computed; "
            "a zero in place of a number is forbidden"
        )
    ordered = sorted(values)
    return {
        "n": float(len(ordered)),
        "median": statistics.median(ordered),
        "p95": _quantile(ordered, 0.95),
        "max": ordered[-1],
    }


def _scaled_distribution(values: list[float], what: str, scale: float) -> dict[str, float]:
    distribution = _distribution(values, what)
    scaled = {name: value / scale for name, value in distribution.items() if name != "n"}
    scaled["n"] = float(len(values))
    return scaled


def _adjacent_pairs(actual: list[float]) -> list[tuple[int, int]]:
    if len(actual) < 2:
        raise MetricsReportError(
            "the effect error requires at least two scenarios: there is no "
            "difference within a single scenario"
        )
    order = sorted(range(len(actual)), key=lambda i: actual[i], reverse=True)
    return list(zip(order, order[1:]))


def _effect_error(
    actual: list[float],
    predicted: list[float],
    *,
    threshold_rub: float = EFFECT_THRESHOLD_RUB,
) -> dict[str, object]:
    if len(actual) != len(predicted):
        raise MetricsReportError(
            f"{len(actual)} scenarios in fact and {len(predicted)} in the prediction"
        )
    if threshold_rub <= 0.0:
        raise MetricsReportError(
            "the significance threshold of the NPV difference must be positive"
        )
    pairs = _adjacent_pairs(actual)
    relative: list[float] = []
    absolute: list[float] = []
    degenerate: list[float] = []
    rows: list[dict[str, object]] = []
    for position, (high, low) in enumerate(pairs, start=1):
        true_delta = actual[high] - actual[low]
        predicted_delta = predicted[high] - predicted[low]
        error = abs(predicted_delta - true_delta)
        absolute.append(error)
        significant = abs(true_delta) >= threshold_rub
        share = error / abs(true_delta) * 100.0 if significant else None
        if significant:
            relative.append(share)
        else:
            degenerate.append(error)
        rows.append(
            {
                "pair_rank": position,
                "index_high": high,
                "index_low": low,
                "true_delta_rub": true_delta,
                "predicted_delta_rub": predicted_delta,
                "absolute_error_rub": error,
                "relative_error_pct": share,
                "significant": significant,
                "sign_agrees": (predicted_delta > 0.0) == (true_delta > 0.0),
            }
        )
    payload: dict[str, object] = {
        "pairing": "adjacent pairs in the true-NPV ranking",
        "pairing_rationale": (
            "the optimizer chooses between neighbours in the ranking, so the "
            "error measured is exactly that of the difference the decision is made on; "
            "taking all pairs of the sample overstates quality thanks to distant pairs, "
            "and schedule proximity cannot be recovered from the artifact"
        ),
        "n_pairs": len(pairs),
        "significance_threshold_rub": threshold_rub,
        "n_significant_pairs": len(relative),
        "n_degenerate_pairs": len(degenerate),
        "degenerate_policy": (
            "a pair whose |true difference| is below the threshold does not enter "
            "the relative error and is counted separately by the absolute one: "
            "dividing by nearly zero measures the division, not the model"
        ),
        "absolute_error_mln_rub": _scaled_distribution(
            absolute, "absolute effect error", 1e6
        ),
        "sign_agreement": sum(1 for row in rows if row["sign_agrees"]) / len(rows),
        "rows": rows,
    }
    if relative:
        distribution = _distribution(relative, "relative effect error")
        payload["effect_error_pct_median"] = distribution["median"]
        payload["effect_error_pct_p95"] = distribution["p95"]
        payload["effect_error_pct_max"] = distribution["max"]
    else:
        payload["effect_error_pct_median"] = None
        payload["effect_error_pct_p95"] = None
        payload["effect_error_pct_max"] = None
        payload["relative_error_unavailable"] = (
            f"none of the {len(pairs)} pairs has a true NPV difference above "
            f"{threshold_rub:.0f} RUB: the relative effect error is undefined on "
            "this sample, read the absolute one"
        )
    if degenerate:
        payload["degenerate_absolute_error_mln_rub"] = _scaled_distribution(
            degenerate, "absolute error of degenerate pairs", 1e6
        )
    return payload


def _bhp_absolute_errors(
    predicted_states: Sequence[StateAtDate], actual_states: Sequence[StateAtDate]
) -> list[float]:
    by_key = {(state.well, state.deck_date_index): state for state in actual_states}
    if len(by_key) != len(actual_states):
        raise MetricsReportError(
            "the pair (well, deck date) occurs twice in the actual states"
        )
    errors: list[float] = []
    for state in predicted_states:
        fact = by_key.get((state.well, state.deck_date_index))
        if fact is None:
            raise MetricsReportError(
                f"no actual state for {state.well} at deck step "
                f"{state.deck_date_index}: there is nothing to compare the bhp channel against"
            )
        errors.append(abs(state.bhp - fact.bhp))
    if not errors:
        raise MetricsReportError(
            "bhp channel: not a single predicted state, the distribution is not computed"
        )
    return errors


def _bhp_channel(per_scenario: list[tuple[str, list[float]]]) -> dict[str, object]:
    if not per_scenario:
        raise MetricsReportError(
            "bhp channel: not a single scenario with an OPM response; delta for "
            "SRCH-14 is not produced without ground truth"
        )
    pooled: list[float] = []
    for _, errors in per_scenario:
        pooled.extend(errors)
    distribution = _distribution(pooled, "bhp channel error")
    return {
        "channel": "bhp",
        "unit": "bar",
        "source": "StateAtDate.bhp: surrogate prediction against the OPM response",
        "consumer": "SRCH-14: delta for aligning the BHP gates between search and submission",
        "n_states": int(distribution["n"]),
        "n_scenarios": len(per_scenario),
        "bhp_error_bar_median": distribution["median"],
        "bhp_error_bar_p95": distribution["p95"],
        "bhp_error_bar_max": distribution["max"],
        "per_scenario": [
            {
                "run": name,
                "n_states": int(_distribution(errors, "bhp channel error")["n"]),
                "bhp_error_bar_median": _distribution(errors, "bhp channel error")["median"],
                "bhp_error_bar_p95": _distribution(errors, "bhp channel error")["p95"],
            }
            for name, errors in per_scenario
        ],
    }


def _held_out(args, env, labels: dict, holdout: FrozenHoldout) -> dict[str, object]:
    with _legacy_checkpoint_modules():
        bundle = torch.load(args.tensors, map_location="cpu", weights_only=False, mmap=True)
    identities = bundle["identities"].get(args.split)
    if not identities:
        raise MetricsReportError(f"the tensors contain no split {args.split!r}")
    by_identity = {(r["source_dataset"], r["scenario_id"], r["canonical_schedule_hash"]): r
                   for r in labels["rows"].values()}
    plans = {
        source: {spec.scenario_id: spec for spec in build_plan(env.base_schedule, seed=seed, config=config)}
        for source, seed, config in (("dataset-main", 20260816, PILOT_CONFIG),
                                     ("dataset-extra-500", 20260817, EXTRA_CONFIG))
    }
    rows = []
    seen = set()
    for index, identity in enumerate(identities):
        key = (identity["source_dataset"], identity["scenario_id"], identity["canonical_schedule_hash"])
        label = by_identity.get(key)
        if label is None or label["bucket"] != args.split:
            raise MetricsReportError(f"no exact NPV label in the required split: {key}")
        if key[2] in seen:
            continue
        seen.add(key[2])
        spec = plans[key[0]][key[1]]
        schedule = materialize(env.base_schedule, spec).schedule
        if hash_schedule(schedule) != key[2]:
            raise MetricsReportError(f"the reconstructed schedule diverged from the label: {key}")
        rows.append({**identity, "family": spec.family.value, "npv_opm_rub": float(label["npv_rub"]),
                     **_score_schedule(env, schedule)})
        if (index + 1) % 10 == 0:
            print(f"{args.split}: {index + 1}/{len(identities)}", flush=True)
    assert_holdout_excluded(
        holdout,
        [row["canonical_schedule_hash"] for row in rows],
        f"split {args.split!r} of the tensor cache",
    )
    components = _component_metrics(rows)
    actual = [row["npv_opm_rub"] for row in rows]
    return {
        "population": f"{args.split}: unique schedules, current production blend",
        "note": "diagnostic disclosed split; all predictions evaluated, including OOD",
        **components["blended"],
        "effect": _effect_error(actual, [row["blended"] for row in rows]),
        "bhp_channel_unavailable": (
            "the split labels contain only the OPM NPV, there is no StateAtDate response in them: "
            "the bhp channel error is computed where an OPM response.json is present on disk"
        ),
        "components": components, "rows": rows,
        "by_family": {family: _component_metrics([r for r in rows if r["family"] == family])
                      for family in sorted({r["family"] for r in rows})
                      if sum(r["family"] == family for r in rows) >= 2},
    }


def _manifold(args, env, holdout: FrozenHoldout) -> dict[str, object]:
    directories = sorted(
        path
        for path in args.manifold_root.glob(args.manifold_glob)
        if path.is_dir() and (path / "result.json").is_file()
    )
    if len(directories) < 2:
        raise MetricsReportError(
            f"{args.manifold_root}/{args.manifold_glob}: at least two runs with a real "
            "OPM NPV are required for the ranking to be meaningful"
        )
    physical_weight = float(getattr(env.npv_head, "physical_npv_weight", 0.0))
    actual, predicted, rows = [], [], []
    bhp_per_scenario: list[tuple[str, list[float]]] = []
    missing_response: list[str] = []
    opm_results: list[dict] = []
    for directory in directories:
        schedule = _load_schedule(read_json(directory / 'schedule.json'))
        result = read_json(directory / 'result.json')
        opm_results.append(result)
        if result["canonical_schedule_hash"] != hash_schedule(schedule):
            raise MetricsReportError(f"{directory}: schedule hash differs from OPM result")
        components, response = _predict_response(env, schedule)
        actual.append(float(result["npv_opm"]))
        predicted.append(components["blended"])
        rows.append({"run": directory.name, "npv_opm_rub": actual[-1],
                     "npv_surrogate_rub": predicted[-1], **components})
        opm_response = directory / "response.json"
        if opm_response.is_file():
            bhp_per_scenario.append((
                directory.name,
                _bhp_absolute_errors(
                    response.state_at_date,
                    load_response_artifact(opm_response).state_at_date,
                ),
            ))
        else:
            missing_response.append(directory.name)

    bhp: dict[str, object]
    if bhp_per_scenario:
        bhp = _bhp_channel(bhp_per_scenario)
        if missing_response:
            bhp["scenarios_without_opm_response"] = missing_response
    else:
        bhp = {
            "channel": "bhp",
            "unit": "bar",
            "unavailable": (
                "no run contains a response.json with an OPM response: there is nothing "
                "to compare the bhp channel error against, no number is produced"
            ),
            "scenarios_without_opm_response": missing_response,
        }

    assert_holdout_excluded(
        holdout,
        [result["canonical_schedule_hash"] for result in opm_results],
        "optimizer manifold",
    )
    return {
        "effect": _effect_error(actual, predicted),
        "bhp_channel": bhp,
        "population": "loop candidates with a real OPM NPV",
        "physical_npv_weight": physical_weight,
        "caveat": (
            "eight runs are no substitute for a sealed optimizer-shaped sample; "
            "the G10 pool of 40 candidates is absent from disk, and until a new OPM "
            "batch arrives this table remains indicative"
        ),
        "regression": _regression(actual, predicted),
        "ranking": _ranking(actual, predicted),
        "rows": rows,
        "components": _component_metrics(rows),
    }


if __name__ == "__main__":
    from backend.interfaces.cli.runner import run as run_cli
    from backend.interfaces.cli.surrogate.tools.surrogate_metrics_cli import main

    raise SystemExit(run_cli(main))
