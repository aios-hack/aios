"""Small per-run JSON payload for a UI or a human inspecting one run."""

from __future__ import annotations

import json
from pathlib import Path

from backend.application.runs import RunManifest


def export_run_summary(manifest: RunManifest, out_dir: Path) -> Path:
    """Write only verified workflow facts; never invent a UI result."""
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / "run.json"
    path.write_text(
        json.dumps(manifest.as_dict(), ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return path
