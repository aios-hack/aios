from __future__ import annotations

import json
from pathlib import Path

import pytest

from backend.application.jarvis.artifacts import ArtifactStore
from backend.application.jarvis.knowledge import Knowledge, normalize
from backend.application.jarvis.tools import run_tool
from backend.application.jarvis.tools.actions import WORKSPACE_VIEWS
from backend.application.jarvis.tools.context import (
    ConsoleContext,
    ToolContext,
    ToolFailure,
)

MIN_TERMS = 40
LANGS = ("ru", "en")


@pytest.fixture(scope="module")
def knowledge() -> Knowledge:
    return Knowledge()


def make(store: ArtifactStore, knowledge: Knowledge, **console: object) -> ToolContext:
    return ToolContext(
        store=store, console=ConsoleContext(**console), knowledge=knowledge
    )


def test_glossary_has_enough_terms(knowledge: Knowledge) -> None:
    assert knowledge.term_count >= MIN_TERMS


def test_every_term_is_bilingual_with_a_source(knowledge: Knowledge) -> None:
    for term in knowledge.terms():
        for lang in LANGS:
            assert term.term.get(lang), term.id
            assert term.definition.get(lang), term.id
        assert term.source, term.id
        assert term.where_in_platform, term.id


def test_every_where_in_platform_route_exists(knowledge: Knowledge) -> None:
    for term in knowledge.terms():
        for place in term.where_in_platform:
            views = WORKSPACE_VIEWS.get(str(place["workspace"]))
            assert views is not None, (term.id, place)
            assert str(place["view"]) in views, (term.id, place)


def test_related_terms_all_resolve(knowledge: Knowledge) -> None:
    known = {term.id for term in knowledge.terms()}
    for term in knowledge.terms():
        for related in term.related:
            assert related in known, (term.id, related)


def test_every_rule_r0_r7_is_described(knowledge: Knowledge) -> None:
    for index in range(8):
        found = knowledge.find_term(f"R{index}")
        assert found is not None, index


def test_guide_covers_every_workspace_view(knowledge: Knowledge) -> None:
    declared = {
        (workspace, view)
        for workspace, views in WORKSPACE_VIEWS.items()
        for view in views
    }
    covered = {(screen.workspace, screen.view) for screen in knowledge.screens()}
    assert declared == covered


def test_every_screen_is_bilingual(knowledge: Knowledge) -> None:
    for screen in knowledge.screens():
        for lang in LANGS:
            assert screen.title.get(lang), screen.workspace
            assert screen.what.get(lang), screen.workspace
            assert screen.how_to_read.get(lang), screen.workspace
            assert screen.questions.get(lang), screen.workspace
        assert screen.controls, screen.workspace
        for control in screen.controls:
            for lang in LANGS:
                assert control["label"].get(lang), control
            assert control["spotlight"], control


def test_extra_elements_are_present(knowledge: Knowledge) -> None:
    identifiers = {str(element["id"]) for element in knowledge.elements()}
    assert identifiers == {"header", "player", "inspector", "command-palette"}


def test_spotlight_anchors_are_unique_slugs(knowledge: Knowledge) -> None:
    anchors = knowledge.spotlights()
    assert len(anchors) == len(set(anchors))
    for anchor in anchors:
        assert anchor == anchor.lower()
        assert " " not in anchor


def test_find_term_by_exact_name(knowledge: Knowledge) -> None:
    assert knowledge.find_term("ЧДД").id == "npv"
    assert knowledge.find_term("NPV").id == "npv"


def test_find_term_by_alias(knowledge: Knowledge) -> None:
    assert knowledge.find_term("чистый дисконтированный доход").id == "npv"
    assert knowledge.find_term("wct").id == "watercut"


def test_find_term_tolerates_a_typo(knowledge: Knowledge) -> None:
    assert knowledge.find_term("обводненост").id == "watercut"


def test_find_term_misses_on_nonsense(knowledge: Knowledge) -> None:
    assert knowledge.find_term("погода в Москве") is None


def test_normalize_folds_yo_and_case() -> None:
    assert normalize("Обводнённость") == normalize("обводненность")


def test_explain_term_card(store: ArtifactStore, knowledge: Knowledge) -> None:
    card = run_tool("explain_term", make(store, knowledge), {"query": "ЧДД"})
    assert card.type == "glossary"
    assert card.provenance == "knowledge"
    assert card.payload["id"] == "npv"
    assert card.payload["formula"]
    assert card.payload["unit"]
    assert card.action["workspace"] == "money"
    assert card.action["spotlight"] == "npv-rank-table"


def test_explain_term_english(store: ArtifactStore, knowledge: Knowledge) -> None:
    card = run_tool(
        "explain_term", make(store, knowledge), {"query": "npv", "lang": "en"}
    )
    assert card.payload["term"] == "NPV"


def test_explain_term_miss_is_marked_general(
    store: ArtifactStore, knowledge: Knowledge
) -> None:
    card = run_tool(
        "explain_term", make(store, knowledge), {"query": "погода в Москве"}
    )
    assert card.provenance == "general"
    assert card.payload["provenance"] == "general"
    assert card.payload["definition"] is None
    assert card.action is None


def test_platform_guide_by_context(store: ArtifactStore, knowledge: Knowledge) -> None:
    context = make(store, knowledge, workspace="field", view="projection")
    card = run_tool("platform_guide", context, {})
    assert card.type == "guide"
    assert card.payload["workspace"] == "field"
    assert card.action["spotlight"] == "projection-layer-switch"


def test_platform_guide_by_query(store: ArtifactStore, knowledge: Knowledge) -> None:
    card = run_tool(
        "platform_guide", make(store, knowledge), {"query": "money rank"}
    )
    assert (card.payload["workspace"], card.payload["view"]) == ("money", "rank")


def test_platform_guide_unknown_screen_refuses(
    store: ArtifactStore, knowledge: Knowledge
) -> None:
    with pytest.raises(ToolFailure) as error:
        run_tool(
            "platform_guide", make(store, knowledge), {"query": "квантовый отсек"}
        )
    assert "no such screen" in str(error.value)


def test_knowledge_files_are_valid_json(knowledge_root: Path) -> None:
    for name in ("glossary.json", "guide.json"):
        payload = json.loads((knowledge_root / name).read_text(encoding="utf-8"))
        assert payload["version"] == 1
        assert payload["notice"]["ru"] and payload["notice"]["en"]
