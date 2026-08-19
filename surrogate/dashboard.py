"""Password-protected read-only dashboard for long Model_Z cycles."""

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


_HTML = r"""<!doctype html>
<html lang="ru"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>AIOS · Model_Z cycle</title>
<style>
:root{color-scheme:dark;--bg:#070b12;--panel:#0e1521;--line:#213149;--muted:#8290a7;--text:#edf3ff;--cyan:#43d9d0;--blue:#619bff;--amber:#ffbc57;--red:#ff667a;--green:#6ee7a8}
*{box-sizing:border-box}body{margin:0;background:radial-gradient(circle at 12% -10%,#13233c 0,transparent 35%),var(--bg);color:var(--text);font:14px/1.45 ui-monospace,SFMono-Regular,Menlo,monospace}
main{width:min(1440px,calc(100% - 32px));margin:0 auto;padding:28px 0 48px}.top{display:flex;justify-content:space-between;gap:20px;align-items:flex-start;margin-bottom:22px}.eyebrow{color:var(--cyan);letter-spacing:.16em;text-transform:uppercase;font-size:11px}.title{font:600 clamp(28px,4vw,48px)/1.05 Inter,system-ui,sans-serif;margin:6px 0}.sub{color:var(--muted)}.live{display:flex;gap:9px;align-items:center;color:var(--green);padding-top:8px}.dot{width:8px;height:8px;border-radius:50%;background:currentColor;box-shadow:0 0 16px currentColor;animation:p 1.6s infinite}@keyframes p{50%{opacity:.35}}
.tabs{display:flex;gap:8px;overflow:auto;margin:0 0 16px}.tab{appearance:none;border:1px solid var(--line);background:#0b121d;color:var(--muted);border-radius:10px;padding:10px 14px;font:inherit;white-space:nowrap;cursor:pointer}.tab.active{color:var(--text);border-color:var(--cyan);box-shadow:inset 0 -2px var(--cyan)}.grid{display:grid;grid-template-columns:repeat(12,1fr);gap:14px}.card{background:linear-gradient(180deg,rgba(19,29,44,.96),rgba(12,18,29,.96));border:1px solid var(--line);border-radius:14px;padding:18px;min-width:0;box-shadow:0 14px 38px #0004}.hero{grid-column:span 8}.system{grid-column:span 4}.half{grid-column:span 6}.full{grid-column:1/-1}.label{color:var(--muted);font-size:11px;letter-spacing:.12em;text-transform:uppercase}.big{font:600 clamp(34px,5vw,58px)/1 Inter,system-ui,sans-serif;margin:12px 0 6px}.big small{font-size:.32em;color:var(--muted)}
.bar{height:10px;background:#070b12;border:1px solid #1b2a40;border-radius:99px;overflow:hidden;margin:18px 0 8px}.fill{height:100%;width:0;background:linear-gradient(90deg,var(--blue),var(--cyan));transition:width .5s}.row{display:flex;justify-content:space-between;gap:12px}.stats{display:grid;grid-template-columns:repeat(3,1fr);gap:12px;margin-top:18px}.stat{border-left:2px solid var(--line);padding-left:10px}.value{font-size:20px;margin-top:4px}.meter{margin-top:14px}.meter .bar{height:6px;margin:6px 0}.families{display:grid;gap:12px;margin-top:16px}.family-line{display:grid;grid-template-columns:120px 1fr 60px;gap:12px;align-items:center}.family-line .bar{margin:0;height:7px}.table{width:100%;border-collapse:collapse;margin-top:12px}.table td,.table th{padding:9px 8px;border-bottom:1px solid #1b2739;text-align:left}.table th{color:var(--muted);font-weight:400;font-size:11px}.ok{color:var(--green)}.bad{color:var(--red)}.warn{color:var(--amber)}canvas{width:100%;height:220px;margin-top:12px}.metrics{display:grid;grid-template-columns:repeat(auto-fit,minmax(190px,1fr));gap:10px;margin-top:14px}.metric{background:#09101a;border:1px solid #1b2a40;border-radius:10px;padding:12px}.metric b{display:block;font-size:19px;margin-top:5px}.training-state{font:600 clamp(24px,3vw,38px)/1.15 Inter,system-ui,sans-serif;margin:10px 0}.error{color:var(--red);white-space:pre-wrap;margin-top:12px}.muted{color:var(--muted)}@media(max-width:900px){.hero,.system,.half{grid-column:1/-1}.top{display:block}.stats{grid-template-columns:1fr 1fr}.family-line{grid-template-columns:90px 1fr 50px}}
</style></head><body><main>
<div class="top"><div><div class="eyebrow">Reservoir surrogate telemetry</div><h1 class="title">Model_Z training cycle</h1><div class="sub" id="updated">Подключение…</div></div><div class="live"><span class="dot"></span><span id="stage">LIVE</span></div></div>
<nav class="tabs" id="tabs" aria-label="Этапы вычислительного цикла"></nav>
<div class="grid">
<section class="card hero"><div class="label">OPM Flow · прогресс плана</div><div class="big"><span id="done">—</span><small> / <span id="target">—</span></small></div><div class="bar"><div class="fill" id="progress"></div></div><div class="row muted"><span id="percent">—</span><span id="eta">ETA —</span></div><div class="stats"><div class="stat"><div class="label">Активно</div><div class="value" id="active">—</div></div><div class="stat"><div class="label">Ошибки</div><div class="value" id="failed">—</div></div><div class="stat"><div class="label">Медиана</div><div class="value" id="median">—</div></div></div></section>
<section class="card system"><div class="label">Сервер</div><div class="meter"><div class="row"><span>Load / CPU</span><span id="cpu">—</span></div><div class="bar"><div class="fill" id="cpuBar"></div></div></div><div class="meter"><div class="row"><span>RAM</span><span id="ram">—</span></div><div class="bar"><div class="fill" id="ramBar"></div></div></div><div class="meter"><div class="row"><span>Disk</span><span id="disk">—</span></div><div class="bar"><div class="fill" id="diskBar"></div></div></div><div class="stats"><div class="stat"><div class="label">vCPU</div><div class="value" id="cores">—</div></div><div class="stat"><div class="label">Контейнеры</div><div class="value" id="containers">—</div></div><div class="stat"><div class="label">Датасет</div><div class="value" id="size">—</div></div></div></section>
<section class="card half"><div class="label">Семейства сценариев</div><div class="families" id="families"></div></section>
<section class="card half"><div class="label">Последние завершённые</div><table class="table"><thead><tr><th>Сценарий</th><th>Тип</th><th>Время</th><th>Статус</th></tr></thead><tbody id="recent"></tbody></table></section>
<section class="card full"><div class="label">Статус обучения модели</div><div class="training-state" id="trainingState">Ожидает запуска</div><div class="metrics" id="trainingDetails"></div><div class="error" id="trainingError"></div></section>
<section class="card half"><div class="label">Train / validation loss</div><canvas id="loss" width="900" height="250"></canvas><div class="muted" id="epoch">Обучение ещё не началось</div></section>
<section class="card half"><div class="label">Holdout-метрики</div><div class="metrics" id="metrics"><div class="muted">Появятся после обучения и оценки.</div></div></section>
</div></main>
<script>
const $=id=>document.getElementById(id), fmt=n=>new Intl.NumberFormat('ru-RU',{maximumFractionDigits:2}).format(n), pct=x=>`${fmt(100*x)}%`;
function duration(s){if(s==null||!isFinite(s))return '—';let h=Math.floor(s/3600),m=Math.floor(s%3600/60);return h?`${h}ч ${m}м`:`${m}м`}
function setBar(id,x){$(id).style.width=`${Math.max(0,Math.min(100,100*x))}%`}
function drawLoss(rows){const c=$('loss'),g=c.getContext('2d'),w=c.width,h=c.height;g.clearRect(0,0,w,h);g.strokeStyle='#213149';g.lineWidth=1;for(let i=1;i<5;i++){let y=i*h/5;g.beginPath();g.moveTo(0,y);g.lineTo(w,y);g.stroke()}if(!rows.length)return;let vals=rows.flatMap(r=>[r.train_loss,r.validation_loss]),lo=Math.min(...vals),hi=Math.max(...vals);if(hi===lo)hi=lo+1;function line(key,color){g.strokeStyle=color;g.lineWidth=3;g.beginPath();rows.forEach((r,i)=>{let x=rows.length===1?0:i*w/(rows.length-1),y=h-12-(r[key]-lo)/(hi-lo)*(h-24);i?g.lineTo(x,y):g.moveTo(x,y)});g.stroke()}line('train_loss','#619bff');line('validation_loss','#43d9d0')}
function metric(label,value){return `<div class="metric"><span class="label">${label}</span><b>${value}</b></div>`}
function loss(v){return v==null?'—':Number(v).toExponential(4)}
let selected=null,last=null;
function render(d){last=d;if(!selected||!d.stages.some(x=>x.id===selected))selected=d.active_stage;let s=d.stages.find(x=>x.id===selected)||d.stages[0],ds=s.dataset,tr=s.training||{history:[],metrics:null},modelTr=(d.stages.find(x=>x.id==='combined-700')||{}).training||{history:[],metrics:null};$('tabs').innerHTML=d.stages.map(x=>`<button class="tab ${x.id===selected?'active':''}" data-id="${x.id}">${x.title} · ${x.status}</button>`).join('');document.querySelectorAll('.tab').forEach(b=>b.onclick=()=>{selected=b.dataset.id;render(last)});let p=ds.target?ds.completed/ds.target:0;
$('updated').textContent=`Обновлено ${new Date(d.now).toLocaleString('ru-RU')} · ${ds.plan_hash||'plan pending'}`;$('stage').textContent=s.status.toUpperCase();$('done').textContent=fmt(ds.completed);$('target').textContent=fmt(ds.target);$('percent').textContent=pct(p);setBar('progress',p);$('eta').textContent=`ETA ${duration(ds.eta_seconds)}`;$('active').textContent=s.id===d.active_stage?d.runtime.active_runs:0;$('failed').textContent=ds.failed;$('median').textContent=duration(ds.median_wallclock_seconds);
$('cpu').textContent=`${fmt(d.system.load1)} / ${d.system.cores}`;setBar('cpuBar',d.system.load1/d.system.cores);$('ram').textContent=`${fmt(d.system.memory_used_gib)} / ${fmt(d.system.memory_total_gib)} GiB`;setBar('ramBar',d.system.memory_fraction);$('disk').textContent=`${fmt(d.system.disk_used_gib)} / ${fmt(d.system.disk_total_gib)} GiB`;setBar('diskBar',d.system.disk_fraction);$('cores').textContent=d.system.cores;$('containers').textContent=d.runtime.docker_containers;$('size').textContent=`${fmt(ds.size_gib)} GiB`;
$('families').innerHTML=Object.entries(ds.families).map(([k,v])=>`<div class="family-line"><span>${k}</span><div class="bar"><div class="fill" style="width:${ds.completed?100*v/ds.completed:0}%"></div></div><span>${v}</span></div>`).join('')||'<div class="muted">Ожидает запуска</div>';$('recent').innerHTML=ds.recent.map(x=>`<tr><td>${x.scenario_id}</td><td>${x.family}</td><td>${duration(x.wallclock_seconds)}</td><td class="${x.status==='OK'?'ok':'bad'}">${x.status}</td></tr>`).join('');
drawLoss(tr.history);$('trainingState').textContent=modelTr.phase_label||'Ожидает запуска';$('trainingState').className=`training-state ${modelTr.failed?'bad':modelTr.complete?'ok':'warn'}`;$('trainingDetails').innerHTML=metric('Фаза',modelTr.phase||'—')+metric('Эпоха',`${modelTr.current_epoch||0} / ${modelTr.max_epochs||'—'}`)+metric('Лучшая эпоха',modelTr.best_epoch||'—')+metric('Train loss',loss(modelTr.train_loss))+metric('Validation loss',loss(modelTr.validation_loss))+metric('Best validation',loss(modelTr.best_validation_loss));$('trainingError').textContent=modelTr.error||'';$('epoch').textContent=tr.history.length?`Эпоха ${tr.history.at(-1).epoch} · best ${tr.best_epoch||'—'}`:modelTr.phase_label||'Обучение ещё не началось';let m=tr.metrics;$('metrics').innerHTML='<div class="muted">Появятся после обучения и оценки.</div>';if(m){let rank=m.ranking||{},state=m.state_mean_per_scenario||{},ood=m.ood||{};$('metrics').innerHTML=metric('Spearman ЧДД',fmt(rank.spearman_rank_correlation))+metric('Precision@1',fmt((rank.precision_at_k||{})['1']))+metric('Regret@1',fmt((rank.regret_at_k_rub||{})['1'])+' ₽')+metric('ACTIVE/SHUT',pct(state.active_shut_accuracy||0))+metric('BHP MAE',fmt(state.bhp_mae_bar)+' bar')+metric('OOD outside',`${ood.n_scenarios_outside||0} / ${ood.n_scenarios||0}`)}}
async function refresh(){try{let r=await fetch('/api/status',{cache:'no-store'});if(!r.ok)throw Error(r.status);render(await r.json())}catch(e){$('updated').textContent=`Нет связи: ${e}`;$('stage').textContent='OFFLINE'}}refresh();setInterval(refresh,5000);
</script></body></html>"""


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
    "waiting_pilot": "Ожидается пилотный датасет",
    "freezing_pilot_200": "Загрузка пилотных 200 прогонов",
    "generating_extra_500": "Загрузка дополнительных 500 прогонов",
    "loading_pilot_200": "Загрузка пилотных 200 прогонов",
    "preparing_training_700": "Подготовка обучения на 700 сценариях",
    "splitting_700": "Разбиение на train / validation / holdout",
    "building_context_700": "Расчёт контекста и матрицы влияния",
    "featureizing_700": "Построение признаков и целевых значений",
    "training_combined_700": "Обучение нейросети",
    "evaluating_700": "Расчёт holdout-метрик",
    "complete": "Обучение и оценка завершены",
    "failed": "Обучение остановлено с ошибкой",
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
            "title": "Пилот 200",
            "status": status(
                "pilot-200", "complete" if pilot["completed"] >= 200 else "running"
            ),
            "dataset": pilot,
            "training": {"history": [], "best_epoch": None, "metrics": None},
        },
        {
            "id": "extra-500",
            "title": "Расширение 500",
            "status": status(
                "extra-500",
                "complete" if extra["completed"] >= 500 else "queued",
            ),
            "dataset": extra,
            "training": {"history": [], "best_epoch": None, "metrics": None},
        },
        {
            "id": "combined-700",
            "title": "Итого 700",
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
    load1 = os.getloadavg()[0]
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
                payload = _HTML.encode("utf-8")
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
    password = os.environ.get("AIOS_DASHBOARD_PASSWORD", "")
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
