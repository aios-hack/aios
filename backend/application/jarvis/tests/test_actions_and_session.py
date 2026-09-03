from __future__ import annotations

import pytest

from backend.application.jarvis.artifacts import ArtifactStore
from backend.application.jarvis.prompt import build_system_prompt
from backend.application.jarvis.session import (
    Exchange,
    SessionError,
    SessionStore,
    check_question,
)
from backend.application.jarvis.suggestions import build_suggestions
from backend.application.jarvis.tools.actions import (
    ROUTE_BY_CARD,
    WORKSPACE_VIEWS,
    RouteError,
    build_action,
    check_route,
)
from backend.application.jarvis.tools.context import ConsoleContext

EXPECTED_VIEWS = {
    "overview": ("fund",),
    "field": ("projection",),
    "history": ("matrix", "wall", "table"),
    "decisions": ("council", "rules"),
    "money": ("rank", "comparison", "constraints"),
}


def test_workspace_views_match_console_context() -> None:
    assert WORKSPACE_VIEWS == EXPECTED_VIEWS


def test_every_card_route_is_valid() -> None:
    for card_type, (workspace, view) in ROUTE_BY_CARD.items():
        assert check_route(workspace, view) == (workspace, view), card_type


def test_unknown_workspace_refused() -> None:
    with pytest.raises(RouteError):
        check_route("engine-room", "fund")


def test_unknown_view_refused() -> None:
    with pytest.raises(RouteError):
        check_route("field", "matrix")


def test_error_card_has_no_action() -> None:
    assert build_action("error", {}, "base") is None


def test_guide_action_carries_spotlight() -> None:
    payload = {
        "workspace": "field",
        "view": "projection",
        "controls": [{"label": "x", "spotlight": "projection-threshold-slider"}],
    }
    action = build_action("guide", payload, "base")
    assert action == {
        "scenario": "base",
        "workspace": "field",
        "view": "projection",
        "spotlight": "projection-threshold-slider",
    }


def test_glossary_action_uses_first_place() -> None:
    payload = {
        "where_in_platform": [
            {"workspace": "money", "view": "rank", "spotlight": "npv-rank-table"}
        ]
    }
    action = build_action("glossary", payload, "base")
    assert action["view"] == "rank"
    assert action["spotlight"] == "npv-rank-table"


def test_glossary_without_places_has_no_action() -> None:
    assert build_action("glossary", {"where_in_platform": []}, "base") is None


def test_check_question_trims() -> None:
    assert check_question("  что с фондом  ") == "что с фондом"


def test_empty_question_refused() -> None:
    with pytest.raises(SessionError):
        check_question("   ")


def test_too_long_question_refused() -> None:
    with pytest.raises(SessionError) as error:
        check_question("a" * 601)
    assert "601 characters" in str(error.value)


def test_session_keeps_six_exchanges() -> None:
    store = SessionStore()
    session = store.get("s1", ConsoleContext())
    for index in range(9):
        session.remember(Exchange(f"q{index}", ("well",), f"a{index}"))
    assert len(session.history) == 6
    assert session.history[0].question == "q3"


def test_session_scene_ids_increment() -> None:
    session = SessionStore().get("s2", ConsoleContext())
    assert session.next_scene_id() == "s-01"
    assert session.next_scene_id() == "s-02"


def test_new_generation_cancels_the_previous() -> None:
    store = SessionStore()
    store.start("s3", ConsoleContext())
    assert store.is_cancelled("s3") is False
    store.cancel("s3")
    assert store.is_cancelled("s3") is True
    store.start("s3", ConsoleContext())
    assert store.is_cancelled("s3") is False


def test_session_requires_an_id() -> None:
    with pytest.raises(SessionError):
        SessionStore().get("")


def test_suggestions_mention_the_selected_well(store: ArtifactStore) -> None:
    items = build_suggestions(
        ConsoleContext(selected_well="13", step=96), store
    )
    assert len(items) == 3
    assert any("13" in item["text"] for item in items)


def test_suggestions_offer_a_total_at_the_horizon_end(store: ArtifactStore) -> None:
    items = build_suggestions(ConsoleContext(step=224), store)
    assert any("ЧДД" in item["text"] for item in items)


def test_suggestions_offer_comparison_off_base(store: ArtifactStore) -> None:
    items = build_suggestions(
        ConsoleContext(scenario="whatif-injection-cut"), store
    )
    assert any("whatif-injection-cut" in item["text"] for item in items)


def test_suggestions_english(store: ArtifactStore) -> None:
    items = build_suggestions(ConsoleContext(lang="en", selected_well="13"), store)
    assert all(item["text"].isascii() for item in items)


def test_system_prompt_states_every_rule() -> None:
    prompt = build_system_prompt(
        ConsoleContext(scenario="base", step=96, selected_well="13"), "ru"
    )
    for marker in (
        "Джарвис",
        "не больше двух фраз",
        "Ни одного числа от себя",
        "explain_term",
        "platform_guide",
        "отказ",
        "на «вы»",
        "В данных фонда этого нет",
        "Язык ответа",
    ):
        assert marker in prompt, marker


def test_system_prompt_carries_console_context() -> None:
    prompt = build_system_prompt(
        ConsoleContext(
            scenario="whatif-injection-cut",
            step=96,
            date="2015-01-01",
            selected_well="13",
            workspace="field",
            view="projection",
        )
    )
    assert "whatif-injection-cut" in prompt
    assert "96" in prompt
    assert "2015-01-01" in prompt
    assert "field/projection" in prompt


def test_system_prompt_switches_language() -> None:
    assert "английском" in build_system_prompt(ConsoleContext(), "en")
