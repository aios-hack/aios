from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping

from backend.contexts.assistant.application.recording_replay import Recording
from backend.contexts.assistant.domain.console_context import ConsoleContext
from backend.shared.json_io import read_json

RECORDINGS_DIR = Path(__file__).resolve().parent / "recordings_data"
RECORDINGS_FILE = "recordings.json"


def build_console(payload: Mapping[str, Any]) -> ConsoleContext:
    return ConsoleContext(**payload)


def build_recording(payload: Mapping[str, Any]) -> Recording:
    return Recording(
        name=str(payload["name"]),
        question=str(payload["question"]),
        console=build_console(payload.get("console") or {}),
        calls=tuple(dict(entry) for entry in payload.get("calls") or ()),
        caption=str(payload["caption"]),
        answer=str(payload.get("answer", "")),
    )


def load_recordings() -> tuple[Recording, ...]:
    payload = read_json(RECORDINGS_DIR / RECORDINGS_FILE)
    if not isinstance(payload, list):
        raise TypeError(f"recording resource {RECORDINGS_FILE}: a list is expected")
    return tuple(build_recording(entry) for entry in payload)


RECORDINGS: tuple[Recording, ...] = load_recordings()
