from backend.core.contracts import EventKind, hash_schedule
from backend.presentation.cli import final_campaign
from tests.application.test_run_workflow import historical_schedule


def test_local_search_is_reproducible_and_preserves_history_and_fixed_events(monkeypatch):
    monkeypatch.setattr(final_campaign, "_injection_transfer_plan", lambda *args: ())
    original = historical_schedule()
    first = list(final_campaign.local_candidates(original, None, 12, 42))
    second = list(final_campaign.local_candidates(original, None, 12, 42))
    assert [hash_schedule(s) for s in first] == [hash_schedule(s) for s in second]
    assert first[0] is original
    assert any(hash_schedule(s) != hash_schedule(original) for s in first[1:])
    for schedule in first:
        assert schedule.initial_state == original.initial_state
        assert schedule.fixed_deck_events == original.fixed_deck_events
        for name in ("t0", "n_intervals", "n_control_dates", "wells", "history_prefix_hash", "fixed_events_hash"):
            assert getattr(schedule.meta, name) == getattr(original.meta, name)
        assert len(schedule.control_events) == len(original.control_events)
        for event in schedule.control_events:
            if event.kind is EventKind.SET_LRAT:
                assert 0 <= event.value <= 500
