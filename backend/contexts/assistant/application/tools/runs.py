from __future__ import annotations

from typing import Any, Mapping

from backend.contexts.assistant.infrastructure.artifacts import (
    CLAIMED_NPV_FIELDS,
    MANIFEST_PROVENANCE_FIELDS,
    NOT_RECORDED,
    RunError,
    RunRecord,
)
from backend.contexts.assistant.application.tools.context import Card, ToolContext, ToolFailure
from backend.contexts.assistant.application.tools.labels import RUN_STATUS_LABELS, pick, title

NUMERIC_MANIFEST_FIELDS: tuple[str, ...] = (
    "predicted_npv",
    "verified_npv",
)
NO_SUBMISSION = "no-submission"
PROVENANCE_MANIFEST = "run-manifest"
PROVENANCE_SUBMISSION = "submission-bundle"


def _record(context: ToolContext, arguments: Mapping[str, Any]) -> RunRecord:
    requested = arguments.get("run_id")
    store = context.run_store()
    try:
        return store.read(str(requested) if requested is not None else None)
    except RunError as error:
        raise ToolFailure(str(error)) from error


def _value(record: RunRecord, name: str) -> Any:
    if not record.recorded(name):
        return None
    return record.manifest[name]


def _missing(record: RunRecord, names: tuple[str, ...]) -> list[str]:
    return [name for name in names if not record.recorded(name)]


def _violations(record: RunRecord) -> dict[str, Any]:
    validation = record.validation
    if validation is None:
        return {
            "recorded": False,
            "dynamic": None,
            "blocking": None,
            "failed_identities": None,
            "opm_status": None,
            "unavailable_reason": (
                "проверка прогона не записана: файла validation/result.json нет, "
                "поэтому число нарушений неизвестно"
            ),
        }
    dynamic = validation.get("dynamic_violations")
    blocking = validation.get("blocking_dynamic_violations")
    identities = validation.get("failed_identities")
    return {
        "recorded": True,
        "dynamic": dynamic if isinstance(dynamic, int) else None,
        "blocking": blocking if isinstance(blocking, int) else None,
        "failed_identities": list(identities)
        if isinstance(identities, (list, tuple))
        else None,
        "opm_status": validation.get("opm_status"),
        "unavailable_reason": None,
    }


def _constraints(record: RunRecord) -> dict[str, Any]:
    report = record.constraints_report
    if report is None:
        return {
            "recorded": False,
            "checks": None,
            "unavailable_reason": (
                "отчёта по ограничениям нет: файл "
                "validation/constraints_report.json не записан"
            ),
        }
    checks = report.get("checks")
    return {
        "recorded": checks is not None,
        "checks": list(checks) if isinstance(checks, (list, tuple)) else None,
        "unavailable_reason": report.get("unavailable_reason"),
    }


def _status_label(record: RunRecord, lang: str) -> str | None:
    status = record.manifest.get("status")
    if not isinstance(status, str):
        return None
    return pick(RUN_STATUS_LABELS, status, lang)


def run_status(context: ToolContext, arguments: Mapping[str, Any]) -> Card:
    record = _record(context, arguments)
    status = record.manifest.get("status")
    if not isinstance(status, str):
        raise ToolFailure(
            f"манифест прогона {record.run_id!r} не содержит статуса: "
            f"{record.directory / 'manifest.json'}; состояние расчёта неизвестно"
        )
    provenance_values = {
        name: _value(record, name) for name in MANIFEST_PROVENANCE_FIELDS
    }
    payload: dict[str, Any] = {
        "run_id": record.run_id,
        "status": status,
        "status_label": _status_label(record, context.lang),
        "schedule_hash": _value(record, "schedule_hash"),
        "predicted_npv": _value(record, "predicted_npv"),
        "verified_npv": _value(record, "verified_npv"),
        "sound": _value(record, "sound"),
        "search_strategy": _value(record, "search_strategy"),
        "provenance_fields": provenance_values,
        "not_recorded": _missing(
            record, NUMERIC_MANIFEST_FIELDS + MANIFEST_PROVENANCE_FIELDS
        ),
        "violations": _violations(record),
        "constraints": _constraints(record),
        "has_submission": record.submission is not None,
        "source": str(record.directory / "manifest.json"),
        "not_recorded_marker": NOT_RECORDED,
    }
    return Card(
        type="run-status",
        title=title("run_status", context.lang, run_id=record.run_id),
        payload=payload,
        provenance=PROVENANCE_MANIFEST,
    )


def submission_summary(context: ToolContext, arguments: Mapping[str, Any]) -> Card:
    record = _record(context, arguments)
    bundle = record.submission
    if bundle is None:
        payload: dict[str, Any] = {
            "run_id": record.run_id,
            "assembled": False,
            "code": NO_SUBMISSION,
            "status": record.manifest.get("status"),
            "claimed_npv_rub": None,
            "hashes": None,
            "schedule_include_present": record.schedule_include,
            "checks": None,
            "reason": (
                f"пакет сдачи прогона {record.run_id!r} не собран: файла "
                f"{record.directory / 'submission' / 'claimed_npv.json'} нет, "
                "заявлять нечего"
            ),
            "source": None,
        }
        return Card(
            type="submission",
            title=title("submission", context.lang, run_id=record.run_id),
            payload=payload,
            provenance=PROVENANCE_SUBMISSION,
        )
    claimed = bundle.get("claimed_npv_rub")
    if not isinstance(claimed, (int, float)) or isinstance(claimed, bool):
        raise ToolFailure(
            f"в пакете сдачи прогона {record.run_id!r} нет числа "
            f"claimed_npv_rub, получено {claimed!r}: заявленный ЧДД не "
            "подставляется вместо записанного"
        )
    hashes = {
        name: bundle.get(name)
        for name in CLAIMED_NPV_FIELDS
        if name != "claimed_npv_rub"
    }
    missing = sorted(name for name, value in hashes.items() if value is None)
    payload = {
        "run_id": record.run_id,
        "assembled": True,
        "code": None,
        "status": record.manifest.get("status"),
        "claimed_npv_rub": float(claimed),
        "hashes": hashes,
        "schedule_include_present": record.schedule_include,
        "checks": {
            "status_ready_to_submit": record.manifest.get("status")
            == "ready_to_submit",
            "schedule_include_present": record.schedule_include,
            "source_run_matches": bundle.get("source_run_id") == record.run_id,
            "schedule_hash_matches": (
                bundle.get("canonical_schedule_hash")
                == record.manifest.get("schedule_hash")
            ),
            "missing_fields": missing,
        },
        "reason": None,
        "source": str(record.directory / "submission" / "claimed_npv.json"),
    }
    return Card(
        type="submission",
        title=title("submission", context.lang, run_id=record.run_id),
        payload=payload,
        provenance=PROVENANCE_SUBMISSION,
    )
