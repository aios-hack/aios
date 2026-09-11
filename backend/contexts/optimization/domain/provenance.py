from __future__ import annotations

from backend.shared.settings import Settings

from backend.contexts.optimization.domain.errors import (
    LambdaDesyncError,
    ScheduleSearchError,
)
import hashlib
import math
from pathlib import Path
from typing import (
    Mapping,
)
from backend.core.contracts import (
    Lambda,
)
from backend.contexts.connectivity.domain.groups import (
    lambda_hash,
)
from backend.contexts.surrogate.infrastructure.model_z_context import ModelZFeatureArtifact


LAMBDA_STRICT_ENV = "AIOS_LAMBDA_STRICT"


def _lambda_strict_enabled(environ: Mapping[str, str] | None = None) -> bool:
    if environ is None:
        return Settings.from_env().lambda_strict
    return Settings.from_env(environ).lambda_strict


def npv_blend_provenance(npv_head: object | None) -> dict[str, str]:
    if npv_head is None:
        return {
            "npv_head_version": "none",
            "npv_blend_mode": "absent: голова прямого прогноза не загружена",
            "npv_physical_weight": "none",
            "npv_direct_weight": "none",
            "npv_physical_ensemble_version": "none",
            "npv_blend_provenance_hash": "none",
        }
    weight = getattr(npv_head, "physical_npv_weight", None)
    if weight is None:
        raise ScheduleSearchError(
            "голова ЧДД не сообщает physical_npv_weight: долю физической части "
            "бленда нельзя записать в провенанс, а прогноз ЧДД без неё "
            "невоспроизводим"
        )
    physical = float(weight)
    if not math.isfinite(physical) or not 0.0 <= physical <= 1.0:
        raise ScheduleSearchError(
            f"доля физической части бленда {physical!r} вне отрезка [0, 1]: "
            "провенанс ЧДД описывал бы несуществующую смесь"
        )
    return {
        "npv_head_version": str(getattr(npv_head, "version", "") or "unversioned"),
        "npv_blend_mode": "direct-only" if physical == 0.0 else "physical-blend",
        "npv_physical_weight": repr(physical),
        "npv_direct_weight": repr(1.0 - physical),
        "npv_physical_ensemble_version": str(
            getattr(npv_head, "physical_ensemble_version", "") or "none"
        ),
        "npv_blend_provenance_hash": str(
            getattr(npv_head, "physical_blend_provenance_hash", "") or "none"
        ),
    }


def _context_lambda_hashes(feature_context: ModelZFeatureArtifact) -> tuple[str, ...]:
    return tuple(lambda_hash(window) for window in feature_context.context.lambda_windows)


def lambda_sync_provenance(
    lambda_: Lambda,
    feature_context: ModelZFeatureArtifact,
    lambda_path: Path | None,
    *,
    strict: bool,
) -> dict[str, str]:
    search_hash = lambda_hash(lambda_)
    context_hashes = _context_lambda_hashes(feature_context)
    record = {
        "lambda_path": "none: связность не измерялась" if lambda_path is None else str(lambda_path),
        "lambda_window": f"{lambda_.window_start}..{lambda_.window_end}",
        "lambda_search_hash": search_hash,
        "lambda_context_hashes": ",".join(context_hashes) if context_hashes else "none",
        "lambda_context_source_hash": feature_context.lambda_source_hash,
        "lambda_context_dataset_hash": feature_context.dataset_hash,
        "lambda_context_training_scenarios": str(feature_context.n_training_scenarios),
        "lambda_strict": "true" if strict else "false",
    }
    if lambda_path is None:
        record["lambda_sync"] = "not-applicable"
        record["lambda_sync_detail"] = (
            "поиск идёт на нулевой связности, сверять с обучающей λ нечего"
        )
        return record
    if not context_hashes:
        message = (
            "контекст признаков не содержит ни одного окна λ: на какой матрице "
            "связности обучались признаки — установить нельзя, поэтому "
            "рассинхронизацию с λ поиска обнаружить невозможно"
        )
        record["lambda_sync"] = "unknown"
        record["lambda_sync_detail"] = message
        if strict:
            raise LambdaDesyncError(message)
        return record
    if search_hash in context_hashes:
        record["lambda_sync"] = "match"
        record["lambda_sync_detail"] = (
            f"λ поиска {search_hash} совпала с окном, на котором обучался контекст"
        )
        return record
    message = (
        f"λ поиска ({lambda_path}, окно {lambda_.window_start}..{lambda_.window_end}, "
        f"хеш {search_hash}) не совпадает ни с одним окном, на котором обучался "
        f"контекст признаков (хеши {', '.join(context_hashes)}): поиск считает на "
        "одной матрице связности, а признаки обучены на другой, поэтому прогноз "
        "смещён систематически и по самому прогнозу это не видно"
    )
    record["lambda_sync"] = "desync"
    record["lambda_sync_detail"] = message
    if strict:
        raise LambdaDesyncError(message)
    return record


def _validate_npv_head_compatibility(
    npv_head: object, model: object, feature_context_path: Path | str
) -> None:
    context_hash = getattr(npv_head, "feature_context_sha256", "")
    if context_hash:
        actual = hashlib.sha256(Path(feature_context_path).read_bytes()).hexdigest()
        if context_hash != actual:
            raise ScheduleSearchError("NPV head обучен на другом feature context")
    elif getattr(npv_head, "dataset_hash", None) != getattr(
        model, "dataset_hash", None
    ):
        raise ScheduleSearchError(
            "NPV head и trajectory model обучены на разных данных"
        )
    if getattr(npv_head, "wells", None) != getattr(model, "wells", None):
        raise ScheduleSearchError(
            "NPV head и trajectory model имеют разный фонд скважин"
        )
    if getattr(npv_head, "static_feature_names", None) != getattr(
        model, "static_feature_names", None
    ):
        raise ScheduleSearchError("NPV head и trajectory model имеют разную статику")
    physical_weight = float(getattr(npv_head, "physical_npv_weight", 0.0))
    if physical_weight > 0.0 and getattr(
        npv_head, "physical_ensemble_version", ""
    ) != getattr(model, "version", None):
        raise ScheduleSearchError(
            "NPV blend заморожен под другую trajectory ensemble"
        )


_AMBIGUOUS_NPV_SCORING = (
    "одновременно заданы аффинная калибровка ЧДД и голова прямого прогноза: "
    "калибровка подобрана на сыром физическом ЧДД и к бленду головы "
    "неприменима — итоговое число было бы посчитано не тем, чем заявлено; "
    "оставьте один механизм"
)


def _validate_npv_scoring_is_unambiguous(
    npv_head: object | None, npv_calibration: object | None
) -> None:
    if npv_head is not None and npv_calibration is not None:
        raise ScheduleSearchError(_AMBIGUOUS_NPV_SCORING)


__all__ = [
    "LAMBDA_STRICT_ENV",
    "lambda_sync_provenance",
    "npv_blend_provenance",
]
