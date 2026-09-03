from __future__ import annotations

import json
from pathlib import Path

import pytest

from backend.application.jarvis.artifacts import ArtifactStore
from backend.application.jarvis.fixtures import replay, to_jsonl
from backend.application.jarvis.knowledge import Knowledge
from backend.application.jarvis.orchestrator import Orchestrator
from backend.application.jarvis.recordings import RECORDINGS
from backend.application.jarvis.session import SessionError, SessionStore
from backend.application.jarvis.tools.context import ConsoleContext
from backend.infrastructure.llm.chat_events import ToolCall
from backend.infrastructure.llm.fake_chat import FakeChatClient

EVENT_ORDER = ("scene", "status", "card", "caption_delta", "caption", "suggestions", "done")


@pytest.fixture(scope="module")
def knowledge() -> Knowledge:
    return Knowledge()


@pytest.mark.parametrize("recording", RECORDINGS, ids=lambda r: r.name)
def test_fixture_replays_byte_for_byte(
    recording, store: ArtifactStore, knowledge: Knowledge, fixtures_root: Path
) -> None:
    produced = to_jsonl(replay(recording, store, knowledge))
    stored = (fixtures_root / f"{recording.name}.jsonl").read_text(encoding="utf-8")
    assert produced == stored


@pytest.mark.parametrize("recording", RECORDINGS, ids=lambda r: r.name)
def test_fixture_event_order_matches_contract(
    recording, fixtures_root: Path
) -> None:
    lines = (fixtures_root / f"{recording.name}.jsonl").read_text(
        encoding="utf-8"
    ).splitlines()
    events = [json.loads(line) for line in lines]
    assert events[0]["type"] == "scene"
    assert events[-1]["type"] == "done"
    assert events[-2]["type"] == "suggestions"
    caption_at = [i for i, e in enumerate(events) if e["type"] == "caption"]
    assert len(caption_at) == 1
    cards_at = [i for i, e in enumerate(events) if e["type"] == "card"]
    assert all(index < caption_at[0] for index in cards_at)
    for event in events:
        assert event["type"] in EVENT_ORDER + ("warning", "error")


@pytest.mark.parametrize("recording", RECORDINGS, ids=lambda r: r.name)
def test_fixture_cards_carry_provenance(recording, fixtures_root: Path) -> None:
    lines = (fixtures_root / f"{recording.name}.jsonl").read_text(
        encoding="utf-8"
    ).splitlines()
    for line in lines:
        event = json.loads(line)
        if event["type"] != "card":
            continue
        assert event["card"]["provenance"]
        assert event["card"]["type"] != "error"


def test_orchestrator_stops_after_max_rounds(
    store: ArtifactStore, knowledge: Knowledge
) -> None:
    call = ToolCall(id="c", name="field_metrics", args={"step": 96})
    client = FakeChatClient(rounds=[[call]] * 10, caption="Итог.")
    orchestrator = Orchestrator(
        client=client, store=store, knowledge=knowledge, max_rounds=2
    )
    events = list(orchestrator.ask("s", "что с фондом", ConsoleContext(step=96)))
    done = [event for event in events if event.type == "done"][0]
    assert done.body["tool_rounds"] == 2
    cards = [event for event in events if event.type == "card"]
    assert len(cards) == 2


def test_tool_failure_becomes_error_card(
    store: ArtifactStore, knowledge: Knowledge
) -> None:
    call = ToolCall(id="c", name="well_snapshot", args={"well": "45"})
    client = FakeChatClient(rounds=[[call]], caption="Такой скважины нет.")
    orchestrator = Orchestrator(client=client, store=store, knowledge=knowledge)
    events = list(orchestrator.ask("s", "что со скважиной 45", ConsoleContext(step=1)))
    cards = [event for event in events if event.type == "card"]
    assert len(cards) == 1
    assert cards[0].body["card"]["type"] == "error"
    assert "well 45" in cards[0].body["card"]["payload"]["message"]
    assert cards[0].body["card"].get("action") is None
    assert any(event.type == "done" for event in events)


def test_unknown_tool_becomes_error_card(
    store: ArtifactStore, knowledge: Knowledge
) -> None:
    call = ToolCall(id="c", name="launch_rocket", args={})
    client = FakeChatClient(rounds=[[call]], caption="Такого нет.")
    orchestrator = Orchestrator(client=client, store=store, knowledge=knowledge)
    events = list(orchestrator.ask("s", "запусти ракету", ConsoleContext()))
    cards = [event for event in events if event.type == "card"]
    assert cards[0].body["card"]["type"] == "error"


def test_invented_number_produces_warning(
    store: ArtifactStore, knowledge: Knowledge
) -> None:
    call = ToolCall(id="c", name="field_metrics", args={"step": 96})
    client = FakeChatClient(
        rounds=[[call]], caption="Фонд заработал 777 555 руб. за шаг."
    )
    orchestrator = Orchestrator(client=client, store=store, knowledge=knowledge)
    events = list(orchestrator.ask("s", "сколько заработали", ConsoleContext(step=96)))
    warnings = [event for event in events if event.type == "warning"]
    assert warnings and warnings[0].body["code"] == "number-dropped"
    caption = [event for event in events if event.type == "caption"][0]
    assert "777 555" not in caption.body["text"]
    assert caption.body["guarded"] is True


def test_cancel_stops_the_stream(store: ArtifactStore, knowledge: Knowledge) -> None:
    sessions = SessionStore()
    call = ToolCall(id="c", name="field_metrics", args={"step": 96})
    client = FakeChatClient(rounds=[[call]] * 3, caption="Итог.")
    orchestrator = Orchestrator(
        client=client, store=store, knowledge=knowledge, sessions=sessions
    )
    stream = orchestrator.ask("s", "что с фондом", ConsoleContext(step=96))
    collected = [next(stream), next(stream)]
    sessions.cancel("s")
    collected.extend(stream)
    assert collected[-1].type == "error"
    assert collected[-1].body["code"] == "cancelled"


def test_session_remembers_the_exchange(
    store: ArtifactStore, knowledge: Knowledge
) -> None:
    sessions = SessionStore()
    call = ToolCall(id="c", name="field_metrics", args={"step": 96})
    client = FakeChatClient(rounds=[[call]], caption="Фонд работает.")
    orchestrator = Orchestrator(
        client=client, store=store, knowledge=knowledge, sessions=sessions
    )
    list(orchestrator.ask("s", "что с фондом", ConsoleContext(step=96)))
    session = sessions.get("s")
    assert len(session.history) == 1
    assert session.history[0].card_types == ("metric",)
    assert session.history[0].caption == "Фонд работает."


def test_history_is_passed_to_the_model(
    store: ArtifactStore, knowledge: Knowledge
) -> None:
    sessions = SessionStore()
    call = ToolCall(id="c", name="field_metrics", args={"step": 96})
    client = FakeChatClient(rounds=[[call]], caption="Фонд работает.")
    orchestrator = Orchestrator(
        client=client, store=store, knowledge=knowledge, sessions=sessions
    )
    list(orchestrator.ask("s", "что с фондом", ConsoleContext(step=96)))
    second = FakeChatClient(rounds=[[call]], caption="И сейчас работает.")
    again = Orchestrator(
        client=second, store=store, knowledge=knowledge, sessions=sessions
    )
    list(again.ask("s", "а сейчас", ConsoleContext(step=96)))
    first_messages = second.calls[0][0]
    assert any("Earlier in this session" in (m.content or "") for m in first_messages)


def test_empty_question_refused(store: ArtifactStore, knowledge: Knowledge) -> None:
    orchestrator = Orchestrator(
        client=FakeChatClient(rounds=[], caption=""),
        store=store,
        knowledge=knowledge,
    )
    with pytest.raises(SessionError):
        list(orchestrator.ask("s", "   ", ConsoleContext()))
