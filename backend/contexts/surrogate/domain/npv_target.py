"""Fail-closed provenance contract for exact scenario-NPV training targets."""

from __future__ import annotations

import hashlib
from typing import Any

from backend.core.contracts import canonical_bytes

TARGET_PROVENANCE_FORMAT = "aios.npv-target-provenance.v2"
TARGET_SOURCE_FILES: tuple[str, ...] = (
    "bridge/response_loader.py",
    "bridge/summary.py",
    "config/__init__.py",
    "config/normatives.py",
    "config/schema.py",
    "contracts/__init__.py",
    "contracts/config.py",
    "contracts/economics.py",
    "contracts/hashing.py",
    "contracts/policy.py",
    "contracts/response.py",
    "contracts/schedule.py",
    "economics/__init__.py",
    "economics/base_case.py",
    "economics/decomposition.py",
    "economics/esp.py",
    "economics/fund.py",
    "economics/ledger.py",
    "economics/methodology_hash.py",
    "economics/normatives_io.py",
    "economics/npv.py",
    "schedule/__init__.py",
    "schedule/lossless.py",
)


def _is_sha256(value: object) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value)
    )


def validate_target_provenance(provenance: object) -> str:
    """Validate completeness and return the canonical target provenance hash."""

    if not isinstance(provenance, dict):
        raise TypeError("target provenance must be an object")
    if (
        provenance.get("format") != TARGET_PROVENANCE_FORMAT
        or provenance.get("target") != "npv_methodology_rub"
    ):
        raise RuntimeError("unsupported target provenance contract")
    source_hashes = provenance.get("source_sha256")
    if not isinstance(source_hashes, dict) or set(source_hashes) != set(
        TARGET_SOURCE_FILES
    ):
        raise RuntimeError("target provenance source population differs")
    digest_fields = list(source_hashes.values()) + [
        provenance.get("methodology_version_hash"),
        provenance.get("model_schedule_sha256"),
        provenance.get("normatives_sha256"),
    ]
    if not all(_is_sha256(value) for value in digest_fields):
        raise RuntimeError("target provenance contains an invalid SHA-256")
    expected = provenance.get("target_provenance_sha256")
    hashable: dict[str, Any] = {
        key: value
        for key, value in provenance.items()
        if key != "target_provenance_sha256"
    }
    actual = hashlib.sha256(canonical_bytes(hashable)).hexdigest()
    if expected != actual:
        raise RuntimeError("target provenance canonical hash differs")
    return actual
