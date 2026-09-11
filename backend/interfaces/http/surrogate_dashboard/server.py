
from __future__ import annotations

import argparse
import base64
import json
import os
import secrets
import shutil
import statistics
import subprocess
from datetime import datetime, timezone
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Sequence
from backend.shared.settings import Settings


TEMPLATE_DIR = Path(__file__).resolve().parent / "templates"
DASHBOARD_TEMPLATE = TEMPLATE_DIR / "dashboard.html"


def dashboard_html() -> str:
    return DASHBOARD_TEMPLATE.read_text(encoding="utf-8")


def _run(command: Sequence[str]) -> str:
    try:
        return subprocess.run(
            command, check=False, capture_output=True, text=True, timeout=5
        ).stdout.strip()
    except (OSError, subprocess.TimeoutExpired):
        return ""


def _directory_size(path: Path) -> int:
    total = 0
    if not path.exists():
        return total
    for root, _, files in os.walk(path):
        for name in files:
            try:
                total += (Path(root) / name).stat().st_size
            except OSError:
                pass
    return total


def _memory() -> tuple[int, int]:
    values: dict[str, int] = {}
    try:
        for line in Path("/proc/meminfo").read_text(encoding="ascii").splitlines():
            key, raw = line.split(":", 1)
            values[key] = int(raw.strip().split()[0]) * 1024
    except (OSError, ValueError):
        return 0, 0
    total = values.get("MemTotal", 0)
    available = values.get("MemAvailable", 0)
    return total, max(0, total - available)


def _json_lines(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return rows
    for line in lines:
        try:
            item = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(item, dict):
            rows.append(item)
    return rows


def _dataset_status(
    dataset_root: Path,
    *,
    target_hint: int,
    active_runs: int,
) -> dict[str, Any]:
    plan_path = dataset_root / "plan.json"
    try:
        plan = json.loads(plan_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        plan = {}
    rows = _json_lines(dataset_root / "manifest.jsonl")
    latest: dict[str, dict[str, Any]] = {}
    order: list[str] = []
    for row in rows:
        scenario = str(row.get("scenario_id", ""))
        if not scenario:
            continue
        latest[scenario] = row
        if scenario in order:
            order.remove(scenario)
        order.append(scenario)
    successful = [row for row in latest.values() if row.get("status") == "OK"]
    failed = [row for row in latest.values() if row.get("status") != "OK"]
    families: dict[str, int] = {}
    for row in successful:
        family = str(row.get("family", "UNKNOWN"))
        families[family] = families.get(family, 0) + 1
    durations = [
        float(row.get("wallclock_seconds", 0.0))
        for row in successful
        if float(row.get("wallclock_seconds", 0.0)) > 0.0
    ]
    median_wallclock = statistics.median(durations) if durations else None
    target = len(plan.get("scenarios", ())) or target_hint
    remaining = max(0, target - len(successful))
    parallelism = max(1, active_runs or 8)
    eta = remaining * median_wallclock / parallelism if median_wallclock else None
    gib = 1024**3
    recent = [latest[key] for key in reversed(order[-8:])]
    return {
        "target": target,
        "completed": len(successful),
        "failed": len(failed),
        "families": dict(sorted(families.items())),
        "median_wallclock_seconds": median_wallclock,
        "eta_seconds": eta,
        "size_gib": _directory_size(dataset_root) / gib,
        "plan_hash": str(plan.get("plan_hash", ""))[:16],
        "recent": recent,
    }


_PHASE_LABELS = {
    "waiting_pilot": "Waiting for the pilot dataset",
    "freezing_pilot_200": "Loading the 200 pilot runs",
    "generating_extra_500": "Loading the 500 extra runs",
    "loading_pilot_200": "Loading the 200 pilot runs",
    "preparing_training_700": "Preparing training on 700 scenarios",
    "splitting_700": "Splitting into train / validation / holdout",
    "building_context_700": "Computing the context and the influence matrix",
    "featureizing_700": "Building features and targets",
    "training_combined_700": "Training the network",
    "evaluating_700": "Computing holdout metrics",
    "complete": "Training and evaluation are complete",
    "failed": "Training stopped with an error",
}


def _training_status(
    root: Path, cycle: dict[str, Any], stage: dict[str, Any]
) -> dict[str, Any]:
    report_path = root / "model-task34-700" / "training_report.json"
    try:
        report = json.loads(report_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        report = {}
    history = [
        row for row in _json_lines(root / "cycle-events.jsonl") if row.get("phase") == "train"
    ]
    started_at = str(stage.get("training_started_at", ""))
    if started_at:
        history = [row for row in history if str(row.get("at", "")) >= started_at]
    if report.get("history"):
        history = report["history"]
    latest = history[-1] if history else {}
    phase = str(cycle.get("phase", "waiting_pilot"))
    best_history = min(history, key=lambda row: row["validation_loss"]) if history else {}
    return {
        "history": history,
        "best_epoch": report.get("best_epoch", stage.get("best_epoch", best_history.get("epoch"))),
        "best_validation_loss": stage.get(
            "best_validation_loss", best_history.get("validation_loss")
        ),
        "current_epoch": stage.get("current_epoch", latest.get("epoch", 0)),
        "max_epochs": stage.get("max_epochs"),
        "train_loss": stage.get("train_loss", latest.get("train_loss")),
        "validation_loss": stage.get(
            "validation_loss", latest.get("validation_loss")
        ),
        "phase": phase,
        "phase_label": _PHASE_LABELS.get(phase, phase.replace("_", " ")),
        "error": cycle.get("error"),
        "failed": phase == "failed",
        "complete": phase == "complete",
        "metrics": report.get("metrics"),
    }


def _combined_dataset(
    pilot: dict[str, Any], extra: dict[str, Any]
) -> dict[str, Any]:
    families: dict[str, int] = {}
    for source in (pilot, extra):
        for family, count in source["families"].items():
            families[family] = families.get(family, 0) + count
    medians = [
        item
        for item in (
            pilot["median_wallclock_seconds"],
            extra["median_wallclock_seconds"],
        )
        if item is not None
    ]
    return {
        "target": 700,
        "completed": pilot["completed"] + extra["completed"],
        "failed": pilot["failed"] + extra["failed"],
        "families": dict(sorted(families.items())),
        "median_wallclock_seconds": statistics.median(medians) if medians else None,
        "eta_seconds": None,
        "size_gib": pilot["size_gib"] + extra["size_gib"],
        "plan_hash": "+".join(
            item for item in (pilot["plan_hash"], extra["plan_hash"]) if item
        ),
        "recent": (extra["recent"] + pilot["recent"])[:8],
    }


def collect_status(root: Path) -> dict[str, Any]:
    docker_names = [
        line
        for line in _run(("docker", "ps", "--format", "{{.Names}}")).splitlines()
        if line
    ]
    active = sum(name.startswith("opm-run-") for name in docker_names)
    pilot = _dataset_status(
        root / "dataset-main", target_hint=200, active_runs=active
    )
    extra = _dataset_status(
        root / "dataset-extra-500", target_hint=500, active_runs=active
    )
    combined = _combined_dataset(pilot, extra)

    try:
        cycle = json.loads((root / "cycle.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        cycle = {}
    configured = {
        str(item.get("id")): item for item in cycle.get("stages", ())
    }
    phase = str(cycle.get("phase", "waiting_pilot"))
    if phase in {"waiting_pilot", "freezing_pilot_200"}:
        active_stage = "pilot-200"
    elif phase == "generating_extra_500":
        active_stage = "extra-500"
    else:
        active_stage = "combined-700"

    def status(stage_id: str, fallback: str) -> str:
        if stage_id == active_stage and phase == "failed":
            return "failed"
        return str(configured.get(stage_id, {}).get("status", fallback))

    combined_stage = configured.get("combined-700", {})
    training = _training_status(root, cycle, combined_stage)
    stages = [
        {
            "id": "pilot-200",
            "title": "Pilot 200",
            "status": status(
                "pilot-200", "complete" if pilot["completed"] >= 200 else "running"
            ),
            "dataset": pilot,
            "training": {"history": [], "best_epoch": None, "metrics": None},
        },
        {
            "id": "extra-500",
            "title": "Extra 500",
            "status": status(
                "extra-500",
                "complete" if extra["completed"] >= 500 else "queued",
            ),
            "dataset": extra,
            "training": {"history": [], "best_epoch": None, "metrics": None},
        },
        {
            "id": "combined-700",
            "title": "Total 700",
            "status": status(
                "combined-700", "complete" if training["metrics"] else "queued"
            ),
            "dataset": combined,
            "training": training,
        },
    ]

    memory_total, memory_used = _memory()
    disk = shutil.disk_usage(root)
    cores = os.cpu_count() or 1
    load1 = os.getloadavg()[0] if hasattr(os, "getloadavg") else None
    gib = 1024**3
    return {
        "now": datetime.now(timezone.utc).isoformat(),
        "phase": phase,
        "active_stage": active_stage,
        "stages": stages,
        "runtime": {
            "active_runs": active,
            "docker_containers": len(docker_names),
        },
        "system": {
            "cores": cores,
            "load1": load1,
            "memory_total_gib": memory_total / gib,
            "memory_used_gib": memory_used / gib,
            "memory_fraction": memory_used / memory_total if memory_total else 0.0,
            "disk_total_gib": disk.total / gib,
            "disk_used_gib": disk.used / gib,
            "disk_fraction": disk.used / disk.total if disk.total else 0.0,
        },
    }


def _handler(root: Path, username: str, password: str):
    expected = "Basic " + base64.b64encode(
        f"{username}:{password}".encode("utf-8")
    ).decode("ascii")

    class Handler(BaseHTTPRequestHandler):
        server_version = "AIOSDashboard/1"

        def _authorized(self) -> bool:
            supplied = self.headers.get("Authorization", "")
            return secrets.compare_digest(supplied, expected)

        def _headers(self, status: HTTPStatus, content_type: str) -> None:
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("X-Frame-Options", "DENY")
            self.send_header(
                "Content-Security-Policy",
                "default-src 'self'; style-src 'unsafe-inline'; script-src 'unsafe-inline'",
            )
            self.end_headers()

        def do_GET(self) -> None:  # noqa: N802
            if not self._authorized():
                self.send_response(HTTPStatus.UNAUTHORIZED)
                self.send_header("WWW-Authenticate", 'Basic realm="AIOS read only"')
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                return
            if self.path == "/":
                payload = dashboard_html().encode("utf-8")
                self._headers(HTTPStatus.OK, "text/html; charset=utf-8")
                self.wfile.write(payload)
                return
            if self.path == "/api/status":
                payload = json.dumps(
                    collect_status(root), ensure_ascii=False, allow_nan=False
                ).encode("utf-8")
                self._headers(HTTPStatus.OK, "application/json; charset=utf-8")
                self.wfile.write(payload)
                return
            self._headers(HTTPStatus.NOT_FOUND, "text/plain; charset=utf-8")

        def do_HEAD(self) -> None:  # noqa: N802
            if not self._authorized():
                self.send_response(HTTPStatus.UNAUTHORIZED)
                self.send_header("WWW-Authenticate", 'Basic realm="AIOS read only"')
                self.end_headers()
                return
            self._headers(HTTPStatus.OK, "text/plain; charset=utf-8")

        def do_POST(self) -> None:  # noqa: N802
            self._headers(HTTPStatus.METHOD_NOT_ALLOWED, "text/plain; charset=utf-8")

        def log_message(self, format: str, *args: object) -> None:
            print(f"{self.address_string()} {format % args}", flush=True)

    return Handler


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8080)
    parser.add_argument("--username", default="aios")
    args = parser.parse_args(argv)
    password = Settings.from_env().dashboard_password
    if not password:
        parser.error("AIOS_DASHBOARD_PASSWORD is required")
    server = ThreadingHTTPServer(
        (args.host, args.port),
        _handler(args.root.resolve(), args.username, password),
    )
    print(f"dashboard listening on {args.host}:{args.port}", flush=True)
    server.serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
