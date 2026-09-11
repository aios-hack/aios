from __future__ import annotations

import json
from pathlib import Path

from backend.contexts.runs.application.workflow import RunManifest


def export_run_summary(manifest: RunManifest, out_dir: Path) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / "run.json"
    path.write_text(
        json.dumps(manifest.as_dict(), ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return path
