from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any

from backend.shared.errors import ValidationError


def read_json(path: str | Path) -> Any:
    target = Path(path)
    try:
        text = target.read_text(encoding="utf-8")
    except OSError as error:
        raise ValidationError(
            f"{target}: unreadable — {error}", code="json.unreadable", path=str(target)
        ) from error
    try:
        return json.loads(text)
    except json.JSONDecodeError as error:
        raise ValidationError(
            f"{target}: does not parse as JSON — {error.msg} "
            f"(line {error.lineno}, column {error.colno})",
            code="json.malformed",
            path=str(target),
        ) from error


def read_optional_json(path: str | Path, default: Any = None) -> Any:
    target = Path(path)
    if not target.is_file():
        return default
    return read_json(target)


def dumps_json(payload: Any) -> str:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2) + "\n"


def write_json(path: str | Path, payload: Any) -> Path:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    text = dumps_json(payload)
    handle = tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", dir=str(target.parent), delete=False, suffix=".tmp"
    )
    try:
        with handle as stream:
            stream.write(text)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(handle.name, target)
    except BaseException:
        Path(handle.name).unlink(missing_ok=True)
        raise
    return target


__all__ = ["dumps_json", "read_json", "read_optional_json", "write_json"]
