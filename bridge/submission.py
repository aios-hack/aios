"""Задача 62, звено А (§10.5): один сервис, `Schedule*` → `FinalNpvArtifact`
с доказуемым происхождением.

```
validate_static(Schedule*) == []                       ── гейт до эмита
OpmDeckEmitter → OPM-дек, content_hash_opm
CachingOpmRunner → OpmRunArtifact, требуется status == OK
ResponseLoader → ResponseArtifact
validate_dynamic == []
Economics → FinalNpvArtifact
```

Шесть обязательных тождеств таблицы §10.5 проверяются здесь явно, одно за
другим, а не полагаются на то, что пайплайн «и так" их не нарушит:
неявная корректность — то, из-за чего звено А вообще понадобилось.
Нарушение любого тождества — `SubmissionTractError`, не тихий возврат
неполного артефакта.

Не строит `SubmissionArtifact` (звено Б) — формат `wells_schedule.inc` не
подтверждён организаторами (§3.1, задача 62B). Когда подтвердят —
отдельная функция в этом же модуле, использующая тот же
`canonical_schedule_hash` как связующий идентификатор между звеньями.
"""

from __future__ import annotations

import shutil
from dataclasses import dataclass
from pathlib import Path

from config import economics_config_hash
from contracts import (
    Config,
    Constraints,
    FinalNpvArtifact,
    OpmRunArtifact,
    ResponseArtifact,
    RunStatus,
    Schedule,
    hash_schedule,
)
from economics import methodology_version_hash
from economics.base_case import analyze_base_case
from schedule import (
    DynamicReport,
    ValidationReport,
    parse_schedule,
    validate_dynamic,
    validate_static,
)

from .cache import CachingOpmRunner, RunCache
from .opm_deck import OpmDeckEmitter
from .response_loader import ResponseLoader, load_density_by_pvtnum
from .runner import OpmRunner

_SCHEDULE_INCLUDE = "Model_Z_sch.inc"


class SubmissionTractError(ValueError):
    """Тождество §10.5 не выполнено — какое именно, в сообщении."""


@dataclass(frozen=True, slots=True)
class SubmissionResult:
    """Полный след звена А: каждый шаг тракта, не только конечный артефакт."""

    static_report: ValidationReport
    opm_run: OpmRunArtifact
    response: ResponseArtifact
    dynamic_report: DynamicReport
    final_npv: FinalNpvArtifact


def _run(
    schedule: Schedule,
    model_dir: Path,
    work_root: Path,
    *,
    use_cache: bool,
) -> tuple[OpmRunArtifact, ResponseArtifact]:
    emitter = OpmDeckEmitter(model_dir)
    deck_dir = work_root / "deck"
    if deck_dir.exists():
        # Эмит детерминирован по (model_dir, schedule) — пересборка не меняет
        # результат (`bridge.base_run.run_base_case` делает то же самое),
        # без очистки повторный вызов на тот же work_root падает на непустой
        # destination (`OpmDeckEmitter.emit`).
        shutil.rmtree(deck_dir)
    deck = emitter.emit(schedule, deck_dir)

    base_runner = OpmRunner(work_root / "runs")
    runner = (
        CachingOpmRunner(base_runner, RunCache(work_root / "cache")) if use_cache else base_runner
    )

    result = runner.run(deck, schedule)
    opm_run = OpmRunArtifact(
        run_id=result.run_id,
        status=result.status,
        deck_hash=result.deck_hash,
        canonical_schedule_hash=result.canonical_schedule_hash,
        summary_hash=result.summary_hash,
        artifacts=result.artifacts,
        wallclock_seconds=result.wallclock_seconds,
        message=result.message,
        content_hash_opm=deck.content_hash_opm,
    )

    if opm_run.status is not RunStatus.OK:
        raise SubmissionTractError(
            f"OpmRunArtifact.status == OK не выполнено: {opm_run.status} — {opm_run.message}"
        )

    recomputed = hash_schedule(schedule)
    if opm_run.canonical_schedule_hash != recomputed:
        raise SubmissionTractError(
            "OpmRunArtifact.canonical_schedule_hash == canonical_schedule_hash "
            f"не выполнено: прогон {opm_run.canonical_schedule_hash}, "
            f"пересчитано на моменте сдачи {recomputed} — расписание подменили "
            "после последнего прогона"
        )

    density_by_pvtnum = load_density_by_pvtnum(model_dir)
    response = ResponseLoader().load(opm_run, deck.summary_plan, schedule, density_by_pvtnum)

    if response.source_run_id != opm_run.run_id:
        raise SubmissionTractError(
            "ResponseArtifact.source_run_id == OpmRunArtifact.run_id не выполнено: "
            f"{response.source_run_id!r} != {opm_run.run_id!r} — ResponseLoader "
            "прочитал артефакты не того запуска"
        )

    return opm_run, response


def submit_schedule(
    schedule: Schedule,
    model_dir: Path,
    work_root: Path,
    config: Config,
    *,
    constraints: Constraints | None = None,
    use_cache: bool = True,
) -> SubmissionResult:
    """`Schedule*` → `FinalNpvArtifact`, все шесть тождеств §10.5 проверены.

    `deck_dates`/`t0_deck_date_index` не аргументы — это свойства дека
    Model_Z (371 календарная дата, историческая часть неизменна), не
    конкретного `Schedule*`: берутся из `model_dir`, не из вызывающего
    кода, чтобы их нельзя было передать рассинхронизированными.
    """

    static_report = validate_static(schedule, constraints)
    if not static_report.ok:
        raise SubmissionTractError(
            f"validate_static(Schedule*) == [] не выполнено: "
            f"{len(static_report.violations)} нарушений, первое — "
            f"{static_report.violations[0]}"
        )

    opm_run, response = _run(schedule, model_dir, work_root, use_cache=use_cache)

    parsed = parse_schedule((Path(model_dir) / _SCHEDULE_INCLUDE).read_bytes())
    # report_undershoot=False: BHP_LIMITED — законный режим контроля, не
    # нарушение («скважина упёрлась в предел 50/300 бар, цель недостигнута»,
    # docs/context/08_contracts.md §8.1). Недостижение цели из-за настоящего
    # физического предела — не то, что ловит гейт «не нарушает динамические
    # ограничения»; для этого есть отдельные BHP_BELOW_PRODUCER_LIMIT/
    # BHP_ABOVE_INJECTOR_LIMIT и BHP_LIMITED_WITHOUT_UNDERSHOOT (реальная
    # нестыковка — режим BHP_LIMITED без просадки факта). Недостижение
    # остаётся в отчёте как диагностика (`dynamic_report.undershooting()`),
    # не как блокирующее нарушение.
    dynamic_report = validate_dynamic(
        schedule,
        response.state_at_date,
        response.interval_response,
        constraints,
        report_undershoot=False,
    )
    if not dynamic_report.ok:
        raise SubmissionTractError(
            f"validate_dynamic == [] не выполнено: "
            f"{len(dynamic_report.report.violations)} нарушений, первое — "
            f"{dynamic_report.report.violations[0]}"
        )

    analysis = analyze_base_case(
        response,
        parsed.dates,
        parsed.t0_deck_date_index,
        config.normatives,
        config.policies,
    )

    final_npv = FinalNpvArtifact(
        npv_table=analysis.table,
        npv_methodology=analysis.table.npv_methodology,
        source_run_id=opm_run.run_id,
        source_response_hash=response.response_hash,
        economics_config_hash=economics_config_hash(config),
        methodology_version_hash=methodology_version_hash(),
    )

    if final_npv.source_run_id != opm_run.run_id or final_npv.source_response_hash != response.response_hash:
        raise SubmissionTractError(
            "FinalNpvArtifact.source_run_id/source_response_hash не совпали с "
            "OpmRunArtifact.run_id/ResponseArtifact.response_hash — в Economics "
            "передали отклик другого прогона"
        )

    return SubmissionResult(
        static_report=static_report,
        opm_run=opm_run,
        response=response,
        dynamic_report=dynamic_report,
        final_npv=final_npv,
    )
