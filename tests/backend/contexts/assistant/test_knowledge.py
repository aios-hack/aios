from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from backend.contexts.assistant.infrastructure.artifacts import ArtifactStore
from backend.contexts.assistant.infrastructure.knowledge import Knowledge, normalize
from backend.contexts.assistant.application.tools import run_tool
from backend.contexts.assistant.application.tools.actions import WORKSPACE_VIEWS
from backend.contexts.assistant.application.tools.context import (
    ConsoleContext,
    ToolContext,
    ToolFailure,
)
from backend.contexts.constraints.domain.constraints import (
    COMPENSATION_ENFORCEMENTS,
    COMPENSATION_SCOPES,
    Constraints,
    compensation_policy,
    water_supply_policy,
)
from backend.contexts.schedule.domain.validate import ViolationKind
from backend.contexts.surrogate.domain.physics_checks import (
    Invariant,
    PhysicsReport,
    Severity,
    severity_of,
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


COMPENSATION_ARTIFACT = "data/compensation-base.json"
ASSIGNED_CORRIDOR = (0.85, 1.15)
QUOTED_SURFACE: dict[str, float] = {
    "min": 1.2016,
    "p05": 1.2138,
    "median": 1.2753,
    "p95": 1.4233,
    "max": 1.4567,
}
QUOTED_RESERVOIR_DIFFERENCE_PERCENT = (0.06, 0.29)
NEW_TERM_IDS = (
    "compensation-violation",
    "compensation-base-measurement",
    "physics-gate",
)


@pytest.fixture(scope="module")
def compensation_base(knowledge_root: Path) -> dict:
    path = knowledge_root.parents[3] / COMPENSATION_ARTIFACT
    if not path.is_file():
        pytest.skip("external OPM compensation artifact is absent; generate with tools/compensation_range.py")
    return json.loads(path.read_text(encoding="utf-8"))


def _term(knowledge: Knowledge, query: str) -> Any:
    found = knowledge.find_term(query)
    assert found is not None, query
    return found


@pytest.mark.parametrize(
    ("query", "identifier"),
    [
        ("COMPENSATION_OUT_OF_CORRIDOR", "compensation-violation"),
        ("COMPENSATION_UNDEFINED", "compensation-violation"),
        ("нарушение компенсации", "compensation-violation"),
        ("компенсация базы", "compensation-base-measurement"),
        ("измеренная компенсация", "compensation-base-measurement"),
        ("физгейт", "physics-gate"),
        ("physics gate", "physics-gate"),
        ("семь инвариантов", "physics-gate"),
        ("physics_admissible", "physics-gate"),
        ("external_water_m3_per_day", "external-water"),
        ("water_supply_unlimited", "external-water"),
        ("fraction_defaulted", "external-water"),
        ("внешняя вода", "external-water"),
    ],
)
def test_new_terms_answer_from_the_base(
    knowledge: Knowledge, query: str, identifier: str
) -> None:
    assert _term(knowledge, query).id == identifier


@pytest.mark.parametrize("identifier", NEW_TERM_IDS)
def test_new_terms_answer_without_a_language_model(
    store: ArtifactStore, knowledge: Knowledge, identifier: str
) -> None:
    term = knowledge.find_term(identifier)
    assert term is not None
    card = run_tool(
        "explain_term", make(store, knowledge), {"query": term.term["ru"]}
    )
    assert card.provenance == "knowledge"
    assert card.payload["id"] == identifier
    assert card.payload["definition"]


def test_compensation_violation_names_both_kinds_and_the_defaults(
    knowledge: Knowledge,
) -> None:
    term = _term(knowledge, "COMPENSATION_UNDEFINED")
    for lang in LANGS:
        text = term.definition[lang]
        assert "COMPENSATION_OUT_OF_CORRIDOR" in text
        assert "COMPENSATION_UNDEFINED" in text
        assert "compensation_enforcement" in text
        assert "diagnostic" in text
        assert "compensation_scope" in text
        assert "field_and_groups" in text


def test_compensation_defaults_match_the_contract(knowledge: Knowledge) -> None:
    policy = compensation_policy(Constraints())
    assert policy.enforcement == "diagnostic"
    assert policy.scope == "field_and_groups"
    assert policy.hard is False
    text = _term(knowledge, "COMPENSATION_UNDEFINED").definition["ru"]
    for scope in COMPENSATION_SCOPES:
        assert scope in text
    for enforcement in COMPENSATION_ENFORCEMENTS:
        assert enforcement in text


def test_compensation_violation_kinds_exist_in_the_domain() -> None:
    assert ViolationKind.COMPENSATION_OUT_OF_CORRIDOR.value == (
        "COMPENSATION_OUT_OF_CORRIDOR"
    )
    assert ViolationKind.COMPENSATION_UNDEFINED.value == "COMPENSATION_UNDEFINED"


def test_quoted_base_numbers_match_the_artifact_on_disk(
    knowledge: Knowledge, compensation_base: dict
) -> None:
    distribution = compensation_base["surface"]["distribution"]
    assert distribution["n_steps"] == 224
    text = _term(knowledge, "компенсация базы").definition["ru"]
    for name, quoted in QUOTED_SURFACE.items():
        assert round(distribution[name], 4) == quoted, name
        assert f"{quoted:.4f}" in text, name
    assert "224" in text


def test_no_base_step_falls_into_the_assigned_corridor(
    knowledge: Knowledge, compensation_base: dict
) -> None:
    low, high = ASSIGNED_CORRIDOR
    steps = compensation_base["surface"]["by_step"]
    assert len(steps) == 224
    inside = [step for step in steps if low <= step["value"] <= high]
    assert inside == []
    text = _term(knowledge, "компенсация базы").definition["ru"]
    assert "0.85" in text
    assert "1.15" in text


def test_quoted_reservoir_difference_matches_the_artifact(
    knowledge: Knowledge, compensation_base: dict
) -> None:
    difference = compensation_base["reservoir"]["relative_difference_to_surface"]
    low, high = QUOTED_RESERVOIR_DIFFERENCE_PERCENT
    assert round(difference["min"] * 100.0, 2) == low
    assert round(difference["max"] * 100.0, 2) == high
    text = _term(knowledge, "компенсация базы").definition["ru"]
    assert "0.06" in text
    assert "0.29" in text


def test_external_water_term_states_the_default_and_the_flag(
    knowledge: Knowledge,
) -> None:
    term = _term(knowledge, "external_water_m3_per_day")
    for lang in LANGS:
        text = term.definition[lang]
        assert "external_water_m3_per_day" in text
        assert "fraction_defaulted" in text
        assert "1.0" in text
        assert "water_supply_unlimited" in text


def test_external_water_defaults_match_the_contract() -> None:
    policy = water_supply_policy(
        Constraints(infrastructure={"external_water_m3_per_day": 500.0})
    )
    assert policy.reinjection_fraction == 1.0
    assert policy.fraction_defaulted is True
    assert policy.unlimited is False
    unlimited = water_supply_policy(
        Constraints(infrastructure={"water_supply_unlimited": True})
    )
    assert unlimited.unlimited is True
    assert unlimited.enabled is False


def test_unlimited_water_with_water_keys_is_refused() -> None:
    with pytest.raises(ValueError) as error:
        water_supply_policy(
            Constraints(
                infrastructure={
                    "water_supply_unlimited": True,
                    "external_water_m3_per_day": 500.0,
                }
            )
        )
    assert "water_supply_unlimited" in str(error.value)


def test_physics_gate_term_names_all_seven_invariants(knowledge: Knowledge) -> None:
    term = _term(knowledge, "физгейт")
    for lang in LANGS:
        text = term.definition[lang]
        for invariant in Invariant:
            assert invariant.value in text, (lang, invariant)
        assert "admissible" in text


def test_physics_gate_severities_match_the_module(knowledge: Knowledge) -> None:
    warnings = [
        invariant
        for invariant in Invariant
        if severity_of(invariant) is Severity.WARNING
    ]
    blocking = [
        invariant
        for invariant in Invariant
        if severity_of(invariant) is Severity.BLOCKING
    ]
    assert warnings == [Invariant.BHP_LIMIT]
    assert len(blocking) == 6
    assert len(list(Invariant)) == 7
    text = _term(knowledge, "физгейт").definition["ru"]
    assert "BHP_LIMIT" in text
    assert "предупреждение" in text
    assert "шесть" in text


def test_physics_gate_admissibility_is_completeness_and_no_blocking() -> None:
    complete = PhysicsReport(
        counts={},
        examples=(),
        evaluated=tuple(Invariant),
        skipped={},
        n_nodes=1,
        n_wells=1,
    )
    assert complete.complete is True
    assert complete.admissible is True
    partial = PhysicsReport(
        counts={},
        examples=(),
        evaluated=tuple(Invariant)[:5],
        skipped={
            Invariant.INJECTION_RESPONSE.value: "нет опоры",
            Invariant.MATERIAL_BALANCE.value: "нет опоры",
        },
        n_nodes=1,
        n_wells=1,
    )
    assert partial.complete is False
    assert partial.admissible is False
    flagged = PhysicsReport(
        counts={Invariant.NON_NEGATIVE.value: 1},
        examples=(),
        evaluated=tuple(Invariant),
        skipped={},
        n_nodes=1,
        n_wells=1,
    )
    assert flagged.blocking_count == 1
    assert flagged.admissible is False
    warned = PhysicsReport(
        counts={Invariant.BHP_LIMIT.value: 3},
        examples=(),
        evaluated=tuple(Invariant),
        skipped={},
        n_nodes=1,
        n_wells=1,
    )
    assert warned.blocking_count == 0
    assert warned.warning_count == 3
    assert warned.admissible is True
