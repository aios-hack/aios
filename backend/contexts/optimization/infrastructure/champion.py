from __future__ import annotations

import json
import math
from pathlib import Path
from backend.shared.json_io import read_json


CONDITION_KEYS = (
    "constraints_hash", "deck_hash", "economics_config_hash",
    "methodology_version_hash", "opm_image", "groups_hash",
)


def promote_champion(path: Path, candidate: dict) -> bool:
    if candidate.get("sound") is not True:
        return False
    value = candidate.get("verified_npv_rub")
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError("champion requires finite OPM NPV")
    for key in (*CONDITION_KEYS, "run_id", "schedule_hash"):
        if not isinstance(candidate.get(key), str) or not candidate[key]:
            raise ValueError(f"champion missing {key}")
    if path.exists():
        current = read_json(path)
        if any(current[key] != candidate[key] for key in CONDITION_KEYS):
            raise ValueError("champions cannot be compared under different conditions")
        if value <= current["verified_npv_rub"]:
            return False
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(candidate, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)
    return True
