from __future__ import annotations

import json
import sys
import tempfile
import time
from dataclasses import fields
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from backend.shared.resources import model_z_dir, normatives_xlsx
from backend.contexts.simulation.application.submission import submit_schedule
from backend.contexts.reservoir.infrastructure.opm_deck import OpmDeckEmitter
from backend.contexts.simulation.infrastructure.runner import deck_hashes, summary_spec_hash
from backend.contexts.constraints.domain.schema import default_config
from backend.contexts.constraints.domain.config import ArtifactHashes
from backend.contexts.constraints.domain.constraints import Constraints
from backend.contexts.policy.domain.policy import Theta
from backend.contexts.economics.domain.economics import LineItems
from backend.shared.hashing import hash_schedule
from backend.contexts.economics.infrastructure.normatives_io import load_normatives
from backend.contexts.economics.application.base_case import load_response_artifact
from backend.contexts.economics.application.base_case import analyze_base_case
from backend.contexts.optimization.application.environment import (
    load_environment,
    make_evaluator,
    make_policy,
)
from backend.contexts.optimization.application.search_use_case import (
    DATASET,
    FINAL_CAP,
    LAMBDA,
    RESPONSE,
    SEED,
)
from backend.contexts.policy.domain.fixed_point import resolve
from backend.contexts.policy.domain.theta import default_theta
from backend.contexts.schedule.domain.canonical import canonical_part_hash

OUT = Path("data/g9-attribution.json")
WORK_ROOT = Path("data/g7-submission")
ARTICLES = tuple(field.name for field in fields(LineItems))
MONEY = tuple(name for name in ARTICLES if name != "df")


def _line(items: LineItems) -> dict[str, float]:
    return {name: float(getattr(items, name)) for name in MONEY}


def _sum_lines(rows) -> dict[str, float]:
    total = {name: 0.0 for name in MONEY}
    for items in rows:
        for name in MONEY:
            total[name] += float(getattr(items, name))
    return total


def main() -> int:
    model_dir = model_z_dir()
    normatives_path = normatives_xlsx()
    env = load_environment(
        model_dir=model_dir,
        normatives_path=normatives_path,
        response_path=RESPONSE,
        checkpoint_path=DATASET / "model.pt",
        feature_context_path=DATASET / "feature_context.json",
        lambda_path=LAMBDA,
    )
    initial = load_response_artifact(RESPONSE)
    evaluator = make_evaluator(env)
    saved = json.loads(Path("data/lambda-window-2007/cmaes.json").read_text(encoding="utf-8"))
    theta = Theta(values=dict(saved["theta"]), bounds=default_theta().bounds)

    started = time.monotonic()
    final = resolve(make_policy(env, theta, {}), evaluator, initial, FINAL_CAP)
    best = max(final.visited, key=lambda item: item.npv)
    schedule = best.schedule
    digest = hash_schedule(schedule)
    print(f"the theta* plan was rebuilt in {time.monotonic() - started:.0f} s, {digest[:12]}...", flush=True)
    if digest != saved["canonical_schedule_hash"]:
        print(f"HASH DIVERGED from the recorded {saved['canonical_schedule_hash']}", flush=True)
        return 3

    normatives = load_normatives(normatives_path)
    emitter = OpmDeckEmitter(model_dir)
    with tempfile.TemporaryDirectory() as scratch:
        deck = emitter.emit(schedule, Path(scratch) / "deck")
        hashes = deck_hashes(deck, schedule)
        summary_hash = summary_spec_hash(deck.summary_plan.spec)
    config = default_config(
        normatives,
        ArtifactHashes(
            deck_hash=hashes.deck_hash,
            history_prefix_hash=canonical_part_hash(schedule.initial_state),
            summary_spec_hash=summary_hash,
            groups_hash="0" * 64,
            dataset_version_hash="0" * 64,
            surrogate_checkpoint_hash="0" * 64,
        ),
        global_seed=SEED,
    )
    started = time.monotonic()
    submission = submit_schedule(
        schedule, model_dir, WORK_ROOT, config, constraints=Constraints(), strict=False
    )
    elapsed = time.monotonic() - started
    if submission.response is None:
        print(f"no response received: status {submission.opm_run.status}", flush=True)
        return 4
    if elapsed > 240.0:
        print(f"WARNING: the pipeline took {elapsed / 60:.1f} min - the cache did not work", flush=True)
    else:
        print(f"response from cache in {elapsed:.0f} s", flush=True)

    ours = analyze_base_case(
        submission.response, env.deck_dates, env.t0_deck_date_index, normatives, env.policies
    )
    base = analyze_base_case(
        initial, env.deck_dates, env.t0_deck_date_index, normatives, env.policies
    )
    gap = ours.npv_methodology - base.npv_methodology
    print(
        f"\nbase {base.npv_methodology / 1e9:.3f} bln, ours "
        f"{ours.npv_methodology / 1e9:.3f} bln, gap {gap / 1e9:+.3f} bln",
        flush=True,
    )

    ours_total = _sum_lines(ours.table.by_year.values())
    base_total = _sum_lines(base.table.by_year.values())
    print("\n=== item - base - ours - difference, bln RUB (undiscounted) ===")
    rows = sorted(MONEY, key=lambda name: -abs(ours_total[name] - base_total[name]))
    for name in rows:
        delta = ours_total[name] - base_total[name]
        if abs(delta) < 1e6 and abs(base_total[name]) < 1e6:
            continue
        print(
            f"  {name:<18} {base_total[name] / 1e9:9.3f} {ours_total[name] / 1e9:9.3f} "
            f"{delta / 1e9:+9.3f}"
        )
    check = ours_total["discounted_fcf"] - base_total["discounted_fcf"]
    print(f"\nreconciliation: the sum of discounted_fcf gives {check / 1e9:+.3f} bln against {gap / 1e9:+.3f}")

    print("\n=== by year, discounted FCF, bln RUB ===")
    for year in sorted(set(ours.table.by_year) | set(base.table.by_year)):
        a = base.table.by_year.get(year)
        b = ours.table.by_year.get(year)
        av = a.discounted_fcf if a else 0.0
        bv = b.discounted_fcf if b else 0.0
        if abs(bv - av) < 5e6:
            continue
        print(f"  {year}  {av / 1e9:8.3f} {bv / 1e9:8.3f} {(bv - av) / 1e9:+8.3f}")

    print("\n=== twenty wells with the largest divergence, mln RUB ===")
    wells = set(ours.table.by_well) | set(base.table.by_well)
    diffs = []
    for well in wells:
        a = base.table.by_well.get(well)
        b = ours.table.by_well.get(well)
        av = a.discounted_fcf if a else 0.0
        bv = b.discounted_fcf if b else 0.0
        diffs.append((bv - av, well, av, bv))
    diffs.sort(key=lambda item: abs(item[0]), reverse=True)
    for delta, well, av, bv in diffs[:20]:
        print(f"  well {well:>4}  {av / 1e6:9.1f} {bv / 1e6:9.1f} {delta / 1e6:+9.1f}")
    positive = sum(delta for delta, *_ in diffs if delta > 0)
    negative = sum(delta for delta, *_ in diffs if delta < 0)
    print(
        f"\n  wells in the plus {sum(1 for d, *_ in diffs if d > 0)} for {positive / 1e9:+.3f} bln, "
        f"in the minus {sum(1 for d, *_ in diffs if d < 0)} for {negative / 1e9:+.3f} bln"
    )

    print("\n=== volumes: base - ours - difference ===")
    for name, unit, scale in (
        ("oil_mass_t", "thousand t", 1e3),
        ("liquid_volume_m3", "thousand m3", 1e3),
        ("injection_volume_m3", "thousand m3", 1e3),
        ("active_well_months", "well-months", 1.0),
    ):
        av = float(getattr(base.volumes, name))
        bv = float(getattr(ours.volumes, name))
        print(f"  {name:<20} {av / scale:12.1f} {bv / scale:12.1f} {(bv - av) / scale:+12.1f}  {unit}")

    print("\n=== events: base - ours - difference ===")
    for name in (
        "conversion_count",
        "conversion_cost_rub",
        "stop_start_count",
        "stop_start_cost_rub",
        "commissioning_count",
        "esp_swap_count",
        "esp_capex_rub",
        "esp_swap_opex_rub",
    ):
        av = float(getattr(base.events, name))
        bv = float(getattr(ours.events, name))
        if name.endswith("_rub"):
            print(f"  {name:<22} {av / 1e9:9.3f} {bv / 1e9:9.3f} {(bv - av) / 1e9:+9.3f} bln")
        else:
            print(f"  {name:<22} {av:9.0f} {bv:9.0f} {bv - av:+9.0f}")

    print(
        f"\nrows excluded by the negative rule: base {base.excluded_row_count}, "
        f"ours {ours.excluded_row_count}"
    )

    OUT.write_text(
        json.dumps(
            {
                "npv_base": base.npv_methodology,
                "npv_ours": ours.npv_methodology,
                "gap": gap,
                "canonical_schedule_hash": digest,
                "articles_undiscounted": {
                    name: {
                        "base": base_total[name],
                        "ours": ours_total[name],
                        "delta": ours_total[name] - base_total[name],
                    }
                    for name in MONEY
                },
                "by_year_discounted_fcf": {
                    str(year): {
                        "base": base.table.by_year[year].discounted_fcf
                        if year in base.table.by_year
                        else 0.0,
                        "ours": ours.table.by_year[year].discounted_fcf
                        if year in ours.table.by_year
                        else 0.0,
                    }
                    for year in sorted(set(ours.table.by_year) | set(base.table.by_year))
                },
                "by_well_discounted_fcf_delta": {
                    well: delta for delta, well, _, _ in diffs
                },
                "volumes": {
                    name: {
                        "base": float(getattr(base.volumes, name)),
                        "ours": float(getattr(ours.volumes, name)),
                    }
                    for name in ("oil_mass_t", "liquid_volume_m3", "injection_volume_m3", "active_well_months")
                },
                "events": {
                    name: {
                        "base": float(getattr(base.events, name)),
                        "ours": float(getattr(ours.events, name)),
                    }
                    for name in (
                        "conversion_count",
                        "conversion_cost_rub",
                        "stop_start_count",
                        "stop_start_cost_rub",
                        "commissioning_count",
                        "esp_swap_count",
                        "esp_capex_rub",
                        "esp_swap_opex_rub",
                    )
                },
                "excluded_rows": {"base": base.excluded_row_count, "ours": ours.excluded_row_count},
            },
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    print(f"\nwritten: {OUT}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
