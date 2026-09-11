from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from backend.shared.clock import FrozenClock, SystemClock
from backend.shared.errors import ValidationError
from backend.shared.hashing import canonical_hash, content_hash
from backend.shared.json_io import read_json, read_optional_json, write_json


def test_write_json_sorts_keys_and_ends_with_a_newline(tmp_path: Path) -> None:
    target = write_json(tmp_path / "out.json", {"b": 1, "a": 2})
    text = target.read_text(encoding="utf-8")

    assert text.endswith("\n")
    assert list(json.loads(text)) == ["a", "b"]
    assert text.index('"a"') < text.index('"b"')


def test_write_json_keeps_cyrillic_readable(tmp_path: Path) -> None:
    target = write_json(tmp_path / "out.json", {"подпись": "витрина"})

    assert "витрина" in target.read_text(encoding="utf-8")


def test_write_json_creates_parents_and_replaces_atomically(tmp_path: Path) -> None:
    target = write_json(tmp_path / "deep" / "nested" / "out.json", {"n": 1})
    write_json(target, {"n": 2})

    assert read_json(target) == {"n": 2}
    assert list(target.parent.iterdir()) == [target]


def test_read_json_names_the_file_when_it_is_malformed(tmp_path: Path) -> None:
    broken = tmp_path / "broken.json"
    broken.write_text("{не json", encoding="utf-8")

    with pytest.raises(ValidationError) as error:
        read_json(broken)

    assert error.value.code == "json.malformed"
    assert str(broken) in str(error.value)


def test_read_json_on_a_missing_file_is_a_typed_error(tmp_path: Path) -> None:
    with pytest.raises(ValidationError) as error:
        read_json(tmp_path / "absent.json")

    assert error.value.code == "json.unreadable"


def test_read_optional_json_returns_the_default_when_absent(tmp_path: Path) -> None:
    assert read_optional_json(tmp_path / "absent.json") is None
    assert read_optional_json(tmp_path / "absent.json", {"d": 1}) == {"d": 1}


def test_round_trip_through_write_and_read(tmp_path: Path) -> None:
    payload = {"wells": ["W-1", "W-2"], "steps": [1, 2, 3]}

    assert read_json(write_json(tmp_path / "r.json", payload)) == payload


def test_canonical_hash_ignores_key_order() -> None:
    assert canonical_hash({"a": 1, "b": 2}) == canonical_hash({"b": 2, "a": 1})


def test_content_hash_is_sha256_of_the_bytes() -> None:
    import hashlib

    assert content_hash(b"abc") == hashlib.sha256(b"abc").hexdigest()


def test_frozen_clock_does_not_move_on_its_own() -> None:
    moment = datetime(2026, 9, 11, 12, 0, tzinfo=timezone.utc)
    clock = FrozenClock(moment)

    assert clock.now() == moment
    assert clock.now() == moment


def test_frozen_clock_advances_only_when_asked() -> None:
    clock = FrozenClock(datetime(2026, 9, 11, 12, 0, tzinfo=timezone.utc))
    clock.advance(60)

    assert clock.now() == datetime(2026, 9, 11, 12, 1, tzinfo=timezone.utc)


def test_system_clock_is_timezone_aware() -> None:
    assert SystemClock().now().tzinfo is not None
