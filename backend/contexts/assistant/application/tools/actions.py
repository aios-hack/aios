from __future__ import annotations

from backend.contexts.assistant.domain.errors import (
    RouteError,
)

from typing import Any, Mapping

WORKSPACE_VIEWS: Mapping[str, tuple[str, ...]] = {
    "overview": ("fund",),
    "field": ("projection", "maps"),
    "history": ("matrix", "wall", "table"),
    "decisions": ("council", "rules"),
    "money": ("rank", "comparison", "constraints"),
}
ROUTE_BY_CARD: Mapping[str, tuple[str, str]] = {
    "metric": ("overview", "fund"),
    "well": ("field", "projection"),
    "well-list": ("money", "rank"),
    "field-map": ("field", "projection"),
    "series": ("history", "table"),
    "rule": ("decisions", "rules"),
    "compare": ("money", "comparison"),
    "event-strip": ("history", "matrix"),
    "pattern": ("field", "projection"),
    "glossary": ("overview", "fund"),
    "guide": ("overview", "fund"),
    "status-board": ("money", "comparison"),
    "run-list": ("money", "comparison"),
    "run": ("money", "comparison"),
    "physics": ("money", "comparison"),
    "constraints": ("money", "constraints"),
    "council": ("decisions", "council"),
}


def check_route(workspace: str, view: str) -> tuple[str, str]:
    views = WORKSPACE_VIEWS.get(workspace)
    if views is None:
        raise RouteError(
            f"workspace {workspace} does not exist in the console: available "
            f"workspaces are {', '.join(sorted(WORKSPACE_VIEWS))}"
        )
    if view not in views:
        raise RouteError(
            f"view {view} does not exist in workspace {workspace}: available "
            f"views are {', '.join(views)}"
        )
    return workspace, view


def build_action(
    card_type: str,
    payload: Mapping[str, Any],
    scenario: str,
) -> dict[str, Any] | None:
    if card_type == "error" or card_type == "doc":
        return None
    if card_type == "system-map":
        return _system_map_action(payload, scenario)
    route = ROUTE_BY_CARD.get(card_type)
    if route is None:
        return None
    workspace, view = route
    action: dict[str, Any] = {"scenario": scenario}
    if card_type == "glossary":
        return _knowledge_action(payload, scenario)
    if card_type == "guide":
        return _guide_action(payload, scenario)
    workspace, view = check_route(workspace, view)
    action["workspace"] = workspace
    action["view"] = view
    step = payload.get("step")
    if isinstance(step, int):
        action["step"] = step
    well = payload.get("well")
    if isinstance(well, str):
        action["well"] = well
    if card_type == "well-list":
        rows = payload.get("rows") or ()
        if rows:
            action["well"] = str(rows[0]["well"])
    if card_type == "field-map":
        focus = payload.get("focus") or ()
        if focus:
            action["well"] = str(focus[0])
    if card_type == "event-strip":
        events = payload.get("events") or ()
        if events:
            action["step"] = int(events[0]["step"])
            action["well"] = str(events[0]["well"])
        else:
            from_step = payload.get("from_step")
            if isinstance(from_step, int):
                action["step"] = from_step
    if card_type == "pattern":
        rows = payload.get("patterns") or ()
        if rows:
            action["well"] = str(rows[0]["well"])
            step = rows[0].get("step")
            if isinstance(step, int):
                action["step"] = step
    if card_type == "compare":
        side = payload.get("b") or {}
        identifier = side.get("id")
        if isinstance(identifier, str) and not identifier.startswith(
            ("run-", "web-")
        ):
            action["scenario"] = identifier
    if card_type == "council":
        outcome = payload.get("outcome") or {}
        chosen = outcome.get("well")
        if isinstance(chosen, str):
            action["well"] = chosen
    return action


def _system_map_action(
    payload: Mapping[str, Any], scenario: str
) -> dict[str, Any] | None:
    focus = payload.get("focus")
    for node in payload.get("nodes") or ():
        if not isinstance(node, Mapping):
            continue
        if focus is not None and node.get("id") != focus:
            continue
        route = node.get("route")
        if not isinstance(route, Mapping):
            continue
        workspace = route.get("workspace")
        view = route.get("view")
        if not isinstance(workspace, str) or not isinstance(view, str):
            continue
        workspace, view = check_route(workspace, view)
        return {"scenario": scenario, "workspace": workspace, "view": view}
    return None


def _knowledge_action(payload: Mapping[str, Any], scenario: str) -> dict[str, Any] | None:
    places = payload.get("where_in_platform") or ()
    if not places:
        return None
    place = places[0]
    workspace, view = check_route(str(place["workspace"]), str(place["view"]))
    action: dict[str, Any] = {
        "scenario": scenario,
        "workspace": workspace,
        "view": view,
    }
    spotlight = place.get("spotlight")
    if isinstance(spotlight, str) and spotlight:
        action["spotlight"] = spotlight
    return action


def _guide_action(payload: Mapping[str, Any], scenario: str) -> dict[str, Any] | None:
    workspace = payload.get("workspace")
    view = payload.get("view")
    if not isinstance(workspace, str) or not isinstance(view, str):
        return None
    workspace, view = check_route(workspace, view)
    action: dict[str, Any] = {
        "scenario": scenario,
        "workspace": workspace,
        "view": view,
    }
    controls = payload.get("controls") or ()
    if controls:
        spotlight = controls[0].get("spotlight")
        if isinstance(spotlight, str) and spotlight:
            action["spotlight"] = spotlight
    return action
