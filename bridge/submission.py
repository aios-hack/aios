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

Шесть обязательных тождеств таблицы §10.5 проверяются здесь явно, а не
полагаются на то, что пайплайн «и так» их не нарушит: неявная
корректность — то, из-за чего звено А вообще понадобилось.

**Считаются все шесть и всегда, даже когда первое уже провалилось.** Отчёт,
обрывающийся на первом расхождении, не даёт понять, одна ли вещь сломана
или цепочка разошлась целиком, — а второй попытки сдачи организаторы не
дают [Онб.14]. Исключение бросается один раз, в конце, и перечисляет все
причины сразу. Единственный досрочный обрыв — `validate_static`: за ним
идёт прогон OPM ценой в 10–20 минут, и гонять его для уже отклонённого
расписания незачем.

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
    """Тождество §10.5 не выполнено — какие именно, перечислены в сообщении."""


@dataclass(frozen=True, slots=True)
class IdentityCheck:
    """Одно тождество §10.5: имя, вердикт и что именно разошлось."""

    name: str
    holds: bool
    detail: str


@dataclass(frozen=True, slots=True)
class SubmissionResult:
    """Полный след звена А: каждый шаг тракта, не только конечный артефакт.

    `response`, `dynamic_report` и `final_npv` равны `None` ровно тогда,
    когда цепочка до них не дошла — несошедшийся прогон отклика не даёт, а
    без отклика не считается ни динамика, ни деньги. Подставлять сюда
    правдоподобную заглушку запрещено правилом 6 репозитория.
    """

    static_report: ValidationReport
    opm_run: OpmRunArtifact
    response: ResponseArtifact | None
    dynamic_report: DynamicReport | None
    final_npv: FinalNpvArtifact | None
    identities: tuple[IdentityCheck, ...]

    @property
    def failed_identities(self) -> tuple[IdentityCheck, ...]:
        return tuple(check for check in self.identities if not check.holds)

    @property
    def sound(self) -> bool:
        """Можно ли заявлять число: чистая статика, чистая динамика,
        `status == OK` и все шесть тождеств."""

        return (
            self.static_report.ok
            and self.dynamic_report is not None
            and self.dynamic_report.ok
            and self.opm_run.status is RunStatus.OK
            and self.final_npv is not None
            and all(check.holds for check in self.identities)
        )

    @property
    def npv_methodology(self) -> float:
        """Заявляемое число. Недоступно, пока цепочка не прошла целиком."""

        if not self.sound or self.final_npv is None:
            raise SubmissionTractError(
                "цепочка сдачи не прошла, заявлять число нечем: "
                + _failure_summary(self)
            )
        return self.final_npv.npv_methodology


def _failure_summary(result: SubmissionResult) -> str:
    """Все причины провала разом, а не первая попавшаяся."""

    reasons: list[str] = []
    if not result.static_report.ok:
        reasons.append(
            f"validate_static: {len(result.static_report.violations)} нарушений, "
            f"первое — {result.static_report.violations[0]}"
        )
    if result.dynamic_report is None:
        reasons.append("validate_dynamic не выполнялся: отклик не прочитан")
    elif not result.dynamic_report.ok:
        reasons.append(
            f"validate_dynamic: {len(result.dynamic_report.report.violations)} "
            f"нарушений, первое — {result.dynamic_report.report.violations[0]}"
        )
    reasons.extend(f"{check.name}: {check.detail}" for check in result.failed_identities)
    return "; ".join(reasons)


def _run(
    schedule: Schedule,
    model_dir: Path,
    work_root: Path,
    *,
    use_cache: bool,
) -> tuple[OpmRunArtifact, ResponseArtifact | None]:
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

    # Тождества здесь не проверяются и прогон не обрывается: их считает
    # `_identities` — все шесть и всегда, чтобы отчёт показывал, одна ли вещь
    # сломана или цепочка разошлась целиком. Единственное, что решается тут, —
    # можно ли вообще читать отклик: у несошедшегося прогона его нет.
    if opm_run.status is not RunStatus.OK:
        return opm_run, None

    density_by_pvtnum = load_density_by_pvtnum(model_dir)
    response = ResponseLoader().load(opm_run, deck.summary_plan, schedule, density_by_pvtnum)
    return opm_run, response


def _identities(
    *,
    schedule: Schedule,
    opm_run: OpmRunArtifact,
    response: ResponseArtifact | None,
    final_npv: FinalNpvArtifact | None,
    expected_economics_hash: str,
    expected_methodology_hash: str,
) -> tuple[IdentityCheck, ...]:
    """Все шесть тождеств таблицы §10.5, считаются всегда и целиком.

    Обрыв на первом расхождении не даёт понять, одна ли вещь сломана или
    цепочка разошлась вся, — а вторую попытку сдачи организаторы не дают.
    """

    recomputed = hash_schedule(schedule)
    checks = [
        IdentityCheck(
            name="run_schedule_hash",
            holds=opm_run.canonical_schedule_hash == recomputed,
            detail=(
                f"хеш расписания прогона {opm_run.canonical_schedule_hash!r} против "
                f"пересчитанного на моменте сдачи {recomputed!r} — расписание "
                f"подменили после последнего прогона"
            ),
        ),
        IdentityCheck(
            name="run_status_ok",
            holds=opm_run.status is RunStatus.OK,
            detail=(
                f"status={opm_run.status}: несошедшийся прогон не может быть "
                f"источником заявленного числа ({opm_run.message})"
            ),
        ),
    ]

    if response is None:
        checks.append(
            IdentityCheck(
                name="response_source_run_id",
                holds=False,
                detail="отклик не прочитан: связывать прогон с откликом нечем",
            )
        )
    else:
        checks.append(
            IdentityCheck(
                name="response_source_run_id",
                holds=response.source_run_id == opm_run.run_id,
                detail=(
                    f"ResponseArtifact.source_run_id {response.source_run_id!r} != "
                    f"OpmRunArtifact.run_id {opm_run.run_id!r} — ResponseLoader "
                    f"прочитал артефакты не того запуска"
                ),
            )
        )

    if final_npv is None:
        checks.extend(
            IdentityCheck(
                name=name,
                holds=False,
                detail="ЧДД не посчитан: сверять нечего",
            )
            for name in ("npv_source_provenance", "economics_config_hash", "methodology_version_hash")
        )
        return tuple(checks)

    checks.append(
        IdentityCheck(
            name="npv_source_provenance",
            holds=(
                final_npv.source_run_id == opm_run.run_id
                and response is not None
                and final_npv.source_response_hash == response.response_hash
            ),
            detail=(
                f"FinalNpvArtifact.source_run_id {final_npv.source_run_id!r} / "
                f"source_response_hash {final_npv.source_response_hash!r} не совпали "
                f"с прогоном и откликом — в Economics передали отклик другого "
                f"прогона или подменённый после чтения"
            ),
        )
    )
    checks.append(
        IdentityCheck(
            name="economics_config_hash",
            holds=final_npv.economics_config_hash == expected_economics_hash,
            detail=(
                f"economics_config_hash {final_npv.economics_config_hash!r} != "
                f"пересчитанного {expected_economics_hash!r} — число посчитали с "
                f"другими нормативами"
            ),
        )
    )
    checks.append(
        IdentityCheck(
            name="methodology_version_hash",
            holds=final_npv.methodology_version_hash == expected_methodology_hash,
            detail=(
                f"methodology_version_hash {final_npv.methodology_version_hash!r} != "
                f"пересчитанного {expected_methodology_hash!r} — число посчитали "
                f"другой версией калькулятора"
            ),
        )
    )
    return tuple(checks)


def submit_schedule(
    schedule: Schedule,
    model_dir: Path,
    work_root: Path,
    config: Config,
    *,
    constraints: Constraints | None = None,
    use_cache: bool = True,
    strict: bool = True,
) -> SubmissionResult:
    """`Schedule*` → `FinalNpvArtifact`, все шесть тождеств §10.5 проверены.

    `strict=True` (умолчание) — при непройденном звене А бросает
    `SubmissionTractError`, перечисляя **все** причины сразу.
    `strict=False` возвращает тот же `SubmissionResult` без исключения:
    нужно, когда цепочку разбирают, а не сдают — `result.sound` говорит,
    можно ли заявлять число, `result.failed_identities` — что именно
    разошлось.

    `deck_dates`/`t0_deck_date_index` не аргументы — это свойства дека
    Model_Z (371 календарная дата, историческая часть неизменна), не
    конкретного `Schedule*`: берутся из `model_dir`, не из вызывающего
    кода, чтобы их нельзя было передать рассинхронизированными.
    """

    static_report = validate_static(schedule, constraints)
    if not static_report.ok:
        # Единственное место, где цепочка обрывается досрочно, и обрыв здесь
        # осознан: следующий шаг — прогон OPM ценой в 10–20 минут, а расписание
        # уже отклонено. Дальше по тракту обрывов нет, там отчёт собирается
        # целиком.
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
    dynamic_report = None
    final_npv = None
    expected_economics_hash = economics_config_hash(config)
    expected_methodology_hash = methodology_version_hash()

    if response is not None:
        dynamic_report = validate_dynamic(
            schedule,
            response.state_at_date,
            response.interval_response,
            constraints,
            report_undershoot=False,
        )
        # ЧДД считается и при грязной динамике: заявлять его нельзя (`sound`
        # будет ложным), но в отчёте видно, какое именно число получилось бы —
        # без этого нарушение динамики и ошибка в деньгах неразличимы.
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
            economics_config_hash=expected_economics_hash,
            methodology_version_hash=expected_methodology_hash,
        )

    result = SubmissionResult(
        static_report=static_report,
        opm_run=opm_run,
        response=response,
        dynamic_report=dynamic_report,
        final_npv=final_npv,
        identities=_identities(
            schedule=schedule,
            opm_run=opm_run,
            response=response,
            final_npv=final_npv,
            expected_economics_hash=expected_economics_hash,
            expected_methodology_hash=expected_methodology_hash,
        ),
    )

    if strict and not result.sound:
        raise SubmissionTractError(
            f"звено А §10.5 не пройдено: {_failure_summary(result)}"
        )
    return result
