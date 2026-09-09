from dataclasses import replace

import pytest

from backend.core.contracts import ControlEvent, EventKind
from backend.presentation.cli.surrogate_audit import ranking_metrics
from backend.presentation.cli.surrogate_screen import choose_pair, transfer_fraction
from tests.application.test_run_workflow import historical_schedule


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
