"""Хеш версии кода Economics — формул, не чисел. docs/context/08_contracts.md §10.5, §11.2.

Не строка-версия, которую легко забыть поднять при правке формулы (как
`chdd_model.VERSION` у эталона) — прямой sha256 по байтам файлов, где
живут формулы ЧДД (`npv.py`, `ledger.py`, `decomposition.py`, `fund.py`,
`esp.py`). Любая правка формулы меняет хеш сама, без ручного шага.
`base_case.py` (оркестрация ввода-вывода), `normatives_io.py` (парсинг
xlsx) и `reference_parity.py` (гармонизация с эталоном) сюда не входят —
это не формулы, а обвязка вокруг них.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict
from pathlib import Path
from backend.core.horizon import HORIZON

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
    # Period and discount origin affect money just as surely as formula code.
    digest.update(json.dumps(asdict(HORIZON), default=str, sort_keys=True).encode())
    return digest.hexdigest()
