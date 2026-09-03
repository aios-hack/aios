from __future__ import annotations

from typing import Any, Mapping

WORKSPACE_VIEWS: Mapping[str, tuple[str, ...]] = {
    "overview": ("fund",),
    "field": ("projection",),
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
}


class RouteError(ValueError):
    pass


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
    route = ROUTE_BY_CARD.get(card_type)
    if route is None:
        return None
    if card_type == "error":
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
        if isinstance(identifier, str):
            action["scenario"] = identifier
    return action


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
