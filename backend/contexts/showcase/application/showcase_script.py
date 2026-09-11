from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from backend.contexts.schedule.domain.schedule import N_CONTROL_DATES, T0
from backend.contexts.reservoir.domain.response import N_DECK_DATES

MORPH_HOLD_MS = 5000
EVENT_HOLD_MS = 4500
OPENING_HOLD_MS = 4000
TARGET_TOTAL_MS = 60_000


def _role_and_status(step: dict[str, Any]) -> dict[str, tuple[str, str, str]]:
    return {
        row["well"]: (row["role"], row["availability"], row["operating_status"])
        for row in step["wells"]
    }


def field_events(
    timeline: dict[str, Any], trace: dict[str, dict[str, list[dict[str, Any]]]]
) -> list[dict[str, Any]]:
    steps = timeline["steps"]
    events: list[dict[str, Any]] = []
    previous = _role_and_status(steps[0])
    for step in steps[1:]:
        current = _role_and_status(step)
        control_step = step["control_step"]
        for well in sorted(current, key=lambda name: (len(name), name)):
            was = previous.get(well)
            now = current[well]
            if was is None or was == now:
                continue
            if was[1] != now[1] and now[1] == "AVAILABLE":
                events.append(
                    {"step": control_step, "type": "COMMISSIONED", "well": well}
                )
            if was[0] != now[0]:
                events.append(
                    {"step": control_step, "type": "ROLE_CHANGE", "well": well}
                )
            if was[2] != now[2] and now[2] == "SHUT":
                events.append({"step": control_step, "type": "SHUT", "well": well})
        previous = current
    for well in sorted(trace, key=lambda name: (len(name), name)):
        for raw_step in sorted(trace[well], key=int):
            for record in trace[well][raw_step]:
                events.append(
                    {
                        "step": int(raw_step),
                        "type": "RULE_FIRED",
                        "well": well,
                        "rule": record["rule"],
                    }
                )
    events.sort(key=lambda item: (item["step"], item["type"], item["well"]))
    return events


def _pick_spread(events: list[dict[str, Any]], count: int) -> list[dict[str, Any]]:
    if not events or count <= 0:
        return []
    if len(events) <= count:
        return list(events)
    stride = len(events) / count
    return [events[min(len(events) - 1, int(index * stride))] for index in range(count)]


def build_demo_script(
    timeline: dict[str, Any], trace: dict[str, dict[str, list[dict[str, Any]]]]
) -> dict[str, Any]:
    available = field_events(timeline, trace)
    by_type: dict[str, list[dict[str, Any]]] = {}
    for event in available:
        by_type.setdefault(event["type"], []).append(event)
    frames: list[dict[str, Any]] = [
        {
            "step": 0,
            "scene": "projection",
            "t": 0,
            "well": None,
            "event": None,
            "hold_ms": OPENING_HOLD_MS,
        },
        {
            "step": 0,
            "scene": "projection",
            "t": 1,
            "well": None,
            "event": {"type": "MORPH"},
            "hold_ms": MORPH_HOLD_MS,
        },
    ]
    budget = TARGET_TOTAL_MS - OPENING_HOLD_MS - MORPH_HOLD_MS
    slots = budget // EVENT_HOLD_MS
    order = ("COMMISSIONED", "ROLE_CHANGE", "SHUT", "RULE_FIRED")
    present = [name for name in order if by_type.get(name)]
    if not present:
        return {"frames": frames}
    per_type = max(1, slots // len(present))
    chosen: list[dict[str, Any]] = []
    for name in present:
        chosen.extend(_pick_spread(by_type[name], per_type))
    chosen.sort(key=lambda item: (item["step"], item["type"], item["well"]))
    scenes = ("projection", "chronomap")
    for index, event in enumerate(chosen[:slots]):
        payload: dict[str, Any] = {"type": event["type"], "well": event["well"]}
        if "rule" in event:
            payload["rule"] = event["rule"]
        frames.append(
            {
                "step": event["step"],
                "scene": scenes[index % len(scenes)],
                "well": event["well"],
                "event": payload,
                "hold_ms": EVENT_HOLD_MS,
            }
        )
    return {"frames": frames, "total_ms": sum(frame["hold_ms"] for frame in frames)}


def export_demo_script_json(
    timeline: dict[str, Any],
    trace: dict[str, dict[str, list[dict[str, Any]]]],
    out_path: str | Path,
) -> Path:
    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        json.dumps(
            build_demo_script(timeline, trace),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ),
        encoding="utf-8",
    )
    return out
