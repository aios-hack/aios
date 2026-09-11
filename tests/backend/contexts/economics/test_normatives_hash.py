from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from backend.contexts.economics.infrastructure.normatives_io import (
    NormativesError,
    normatives_sha256,
)


def write_workbook(path: Path, payload: bytes) -> Path:
    path.write_bytes(payload)
    return path


def test_hash_matches_sha256_of_the_file_bytes(tmp_path: Path) -> None:
    payload = b"PK\x03\x04normatives-workbook"
    workbook = write_workbook(tmp_path / "normatives.xlsx", payload)

    assert normatives_sha256(workbook) == hashlib.sha256(payload).hexdigest()


def test_hash_is_stable_across_repeated_reads(tmp_path: Path) -> None:
    workbook = write_workbook(tmp_path / "normatives.xlsx", b"stable-bytes")

    assert normatives_sha256(workbook) == normatives_sha256(workbook)


def test_hash_changes_when_the_file_changes(tmp_path: Path) -> None:
    workbook = write_workbook(tmp_path / "normatives.xlsx", b"oilPriceRubT=25000")
    before = normatives_sha256(workbook)

    write_workbook(workbook, b"oilPriceRubT=26000")

    assert normatives_sha256(workbook) != before


def test_hash_accepts_a_string_path(tmp_path: Path) -> None:
    workbook = write_workbook(tmp_path / "normatives.xlsx", b"bytes")

    assert normatives_sha256(str(workbook)) == normatives_sha256(workbook)


def test_hash_reads_a_file_larger_than_one_chunk(tmp_path: Path) -> None:
    payload = b"x" * (1024 * 1024 + 17)
    workbook = write_workbook(tmp_path / "big.xlsx", payload)

    assert normatives_sha256(workbook) == hashlib.sha256(payload).hexdigest()


def test_missing_file_is_refused_with_its_path(tmp_path: Path) -> None:
    missing = tmp_path / "absent.xlsx"

    with pytest.raises(NormativesError, match="not found"):
        normatives_sha256(missing)


def test_a_directory_is_not_accepted_as_a_workbook(tmp_path: Path) -> None:
    with pytest.raises(NormativesError, match="not found"):
        normatives_sha256(tmp_path)
