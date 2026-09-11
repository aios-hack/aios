from __future__ import annotations

import hashlib
import json
from dataclasses import asdict
from pathlib import Path
from backend.contexts.reservoir.domain.horizon import HORIZON

METHODOLOGY_FILES: tuple[str, ...] = (
    "npv.py",
    "ledger.py",
    "decomposition.py",
    "fund.py",
    "esp.py",
)

_PACKAGE_DIR = Path(__file__).resolve().parent


def methodology_version_hash() -> str:
    digest = hashlib.sha256()
    for name in METHODOLOGY_FILES:
        digest.update((_PACKAGE_DIR / name).read_bytes())
    digest.update(json.dumps(asdict(HORIZON), default=str, sort_keys=True).encode())
    return digest.hexdigest()
