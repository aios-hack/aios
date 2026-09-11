from dataclasses import replace

import pytest

from backend.contexts.schedule.domain.schedule import ControlEvent, EventKind
from backend.interfaces.cli.surrogate.audit import ranking_metrics
from backend.interfaces.cli.surrogate.screen import (
    add_hybrid_scores,
    choose_hybrid_comparison,
    choose_model_comparison,
    choose_pair,
    transfer_fraction,
    water_margins,
    known_schedule_hashes,
)
from tests.backend.contexts.runs.test_run_workflow import historical_schedule


def test_screen_keeps_ood_gate_and_requires_explicit_experiment():
    rows = [dict(schedule_hash=str(i), ranking_score=float(i), ood_score=80,
                 inside_domain=False) for i in range(4)]
    with pytest.raises(ValueError, match="not relaxed"):
        choose_pair(rows, 42)
    top, control = choose_pair(rows, 42, allow_ood=True)
    assert top["schedule_hash"] == "3"
    assert control != top
    assert (top, control) == choose_pair(rows, 42, allow_ood=True)
    rows[-1]["ranking_score"] = float("nan")
    assert choose_pair(rows, 42, allow_ood=True)[0]["schedule_hash"] == "2"


def test_duplicate_schedules_cannot_form_two_experimental_arms():
    row = dict(schedule_hash="same", ranking_score=1., ood_score=0., inside_domain=True)
    with pytest.raises(ValueError):
        choose_pair([row, row], 42)


def test_model_comparison_uses_physical_top_and_direct_head_control():
    rows = [dict(schedule_hash="physical", ranking_score=1., physical_npv=3., ood_score=0., inside_domain=True),
            dict(schedule_hash="direct", ranking_score=4., physical_npv=2., ood_score=0., inside_domain=True),
            dict(schedule_hash="other", ranking_score=0., physical_npv=1., ood_score=0., inside_domain=True)]
    physical, direct = choose_model_comparison(rows, 42)
    assert physical["schedule_hash"] == "physical"
    assert direct["schedule_hash"] == "direct"


def test_hybrid_standardizes_scales_and_uses_complementary_signals():
    rows = [dict(schedule_hash="hybrid", ranking_score=50., physical_npv=100., ood_score=0., inside_domain=True),
            dict(schedule_hash="direct", ranking_score=100., physical_npv=0., ood_score=0., inside_domain=True),
            dict(schedule_hash="low", ranking_score=-100., physical_npv=-100., ood_score=0., inside_domain=True)]
    add_hybrid_scores(rows)
    top, control = choose_hybrid_comparison(rows, 42)
    assert top["schedule_hash"] == "hybrid"
    assert control["schedule_hash"] == "direct"
    assert all("hybrid_score" in row for row in rows)


def test_hybrid_uses_direct_runner_up_when_both_heads_share_top():
    rows = [dict(schedule_hash="shared", ranking_score=10., physical_npv=10., ood_score=0., inside_domain=True),
            dict(schedule_hash="runner-up", ranking_score=9., physical_npv=0., ood_score=0., inside_domain=True),
            dict(schedule_hash="random-loss", ranking_score=-10., physical_npv=1., ood_score=0., inside_domain=True)]
    add_hybrid_scores(rows)
    top, control = choose_hybrid_comparison(rows, 42)
    assert top["schedule_hash"] == "shared"
    assert control["schedule_hash"] == "runner-up"


def test_transfer_conserves_each_interval_even_when_donor_rate_is_tiny():
    schedule = historical_schedule()
    events = (ControlEvent(0, "W1", EventKind.SET_RATE, .2),
              ControlEvent(0, "W2", EventKind.SET_RATE, 10),
              ControlEvent(1, "W1", EventKind.SET_RATE, 0),
              ControlEvent(1, "W2", EventKind.SET_RATE, 20),
              ControlEvent(2, "W1", EventKind.SET_RATE, 4))
    schedule = replace(schedule, control_events=events)
    proposal = transfer_fraction(schedule, "W1", "W2", .5)
    for step in range(3):
        assert sum(e.value for e in proposal.control_events if e.control_step == step) == pytest.approx(
            sum(e.value for e in events if e.control_step == step))
    assert next(e.value for e in proposal.control_events if e.well == "W1" and e.control_step == 0) == .1
    assert proposal.fixed_deck_events == schedule.fixed_deck_events
    assert proposal.initial_state == schedule.initial_state


def test_ranking_metrics_expose_wrong_order_and_regret():
    rows = [dict(run_id="a", predicted_npv=20, measured_npv=10),
            dict(run_id="b", predicted_npv=10, measured_npv=30)]
    result = ranking_metrics(rows)
    assert result["pairwise_accuracy"] == 0
    assert result["top1_regret_rub"] == 20
    assert ranking_metrics([]) == {"n": 0}


def test_default_water_proposals_keep_five_percent_reserve():
    assert water_margins() == (.7, .75, .8, .85, .9, .95)
    assert max(water_margins(.99)) == .99
    with pytest.raises(ValueError):
        water_margins(float("nan"))


def test_known_measurements_are_reused_only_with_identical_conditions(tmp_path, monkeypatch):
    import json
    from types import SimpleNamespace
    from backend.interfaces.cli.surrogate import screen as surrogate_screen
    root = tmp_path / "candidate-001"
    (root / "inputs").mkdir(parents=True)
    (root / "economics").mkdir()
    (root / "inputs/groups.json").write_text("{}")
    champion = dict(constraints_hash="c", deck_hash="d", opm_image="i", groups_hash="g",
                    economics_config_hash="e", methodology_version_hash="m")
    (root / "manifest.json").write_text(json.dumps(dict(champion, sound=False, schedule_hash="s")))
    (root / "economics/result.json").write_text(json.dumps(champion))
    monkeypatch.setattr(surrogate_screen, "load_groups", lambda _: SimpleNamespace(group_hash="g"))
    assert known_schedule_hashes(tmp_path, champion) == {"s"}
    assert known_schedule_hashes(tmp_path, dict(champion, constraints_hash="other")) == set()
    assert known_schedule_hashes(tmp_path, dict(champion, groups_hash="other")) == set()
