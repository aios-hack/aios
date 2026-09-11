from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Mapping

from backend.shared.errors import ConfigurationError
from backend.shared.paths import (
    DATA_ROOT_ENV_VAR,
    DOCS_ROOT_ENV_VAR,
    OUT_ROOT_ENV_VAR,
    PROJECT_ROOT_ENV_VAR,
    data_root,
    out_root,
    project_root,
)

DEFAULT_SEED = 20260816
DEFAULT_LAMBDA_WORKERS = 3
DEFAULT_SEARCH_FIXED_POINT_CAP = 2
DEFAULT_FINAL_FIXED_POINT_CAP = 8
DEFAULT_RISK_AVERSION_BETA = 0.0
DEFAULT_CONSTRAINTS_PATH = Path("config/competition-constraints.json")
DEFAULT_SEARCH_DIAGNOSTICS_PATH = Path("data/lambda-window-2007/cmaes-diagnostics.json")
DEFAULT_SEARCH_RESULT_PATH = Path("data/lambda-window-2007/cmaes.json")
DEFAULT_OPM_IMAGE = "openporousmedia/opmreleases:latest"
DEFAULT_JARVIS_HOST = "127.0.0.1"
DEFAULT_JARVIS_PORT = 8010
DEFAULT_JARVIS_UPSTREAM = "http://127.0.0.1:8010"
DEFAULT_VOICE_RU = "ru-RU-DmitryNeural"
DEFAULT_VOICE_EN = "en-US-AndrewNeural"


def _text(environ: Mapping[str, str], name: str) -> str | None:
    raw = environ.get(name)
    if raw is None:
        return None
    value = raw.strip()
    return value or None


def _path(environ: Mapping[str, str], name: str) -> Path | None:
    value = _text(environ, name)
    return Path(value).expanduser() if value is not None else None


def _integer(environ: Mapping[str, str], name: str, default: int) -> int:
    raw = environ.get(name)
    if raw is None or not raw.strip():
        return default
    try:
        return int(raw)
    except ValueError as error:
        raise ConfigurationError(
            f"{name}={raw!r} — не целое число", code="settings.not_an_integer", variable=name
        ) from error


def _positive_cap(environ: Mapping[str, str], name: str, default: int) -> int:
    raw = environ.get(name)
    if raw is None:
        return default
    try:
        value = int(raw)
    except ValueError as error:
        raise ConfigurationError(
            f"{name}={raw!r} — потолок неподвижной точки задаётся целым числом",
            code="settings.not_an_integer",
            variable=name,
        ) from error
    if value <= 0:
        raise ConfigurationError(
            f"{name}={value} не положителен: потолок неподвижной точки "
            f"берётся снаружи, но обязан допускать хотя бы одну итерацию",
            code="settings.not_positive",
            variable=name,
        )
    return value


def _real(environ: Mapping[str, str], name: str, default: float) -> float:
    raw = environ.get(name)
    if raw is None or not raw.strip():
        return default
    try:
        return float(raw)
    except ValueError as error:
        raise ConfigurationError(
            f"{name}={raw!r} — не вещественное число", code="settings.not_a_number", variable=name
        ) from error


@dataclass(frozen=True, slots=True)
class Settings:
    project_root: Path
    data_root: Path
    out_root: Path
    docs_root: Path | None

    horizon_path: Path | None
    constraints_path: Path
    seed: int

    lambda_root: Path
    lambda_path: Path | None
    lambda_steps: int | None
    lambda_workers: int
    lambda_limit: int | None
    lambda_selection_path: Path | None

    search_diagnostics_path: Path
    search_result_path: Path
    search_fixed_point_cap: int
    final_fixed_point_cap: int
    risk_aversion_beta: float

    compdat_model_dir: Path | None
    base_run_dir: Path | None
    opm_image: str
    opm_budget_journal: Path | None
    opm_run_initiator: str | None

    jarvis_host: str
    jarvis_port: int
    jarvis_upstream: str
    jarvis_config: Path | None
    jarvis_docs: Path | None
    jarvis_knowledge: Path | None
    jarvis_system: Path | None
    jarvis_runs: Path | None
    jarvis_sessions: Path | None
    jarvis_web_runs: Path | None
    jarvis_champion: Path | None
    jarvis_tts_cache: Path | None
    voice_ru: str
    voice_en: str

    openrouter_api_key: str | None
    anthropic_api_key: str | None
    dashboard_password: str

    ui_data_root: Path | None
    surrogate_bundle: Path | None
    surrogate_manifest: Path | None
    checkpoint_dir: Path | None
    checkpoint_path: Path | None
    dataset_root: Path | None
    npv_head_path: Path | None
    npv_calibration_path: Path | None
    ood_calibration_path: Path | None
    ood_threshold: float | None
    scenario_ood_path: Path | None
    feature_context_path: Path | None

    raw: Mapping[str, str] = field(default_factory=dict, repr=False, compare=False)

    @staticmethod
    def from_env(environ: Mapping[str, str] | None = None) -> "Settings":
        source: Mapping[str, str] = os.environ if environ is None else environ
        root = project_root(source)
        data = data_root(source)
        out = out_root(source)
        docs = _path(source, DOCS_ROOT_ENV_VAR)
        lambda_root = _path(source, "AIOS_LAMBDA_ROOT") or (data / "lambda-window-2007")
        ood_threshold_raw = _text(source, "AIOS_OOD_THRESHOLD")
        return Settings(
            project_root=root,
            data_root=data,
            out_root=out,
            docs_root=docs,
            horizon_path=_path(source, "AIOS_HORIZON_PATH"),
            constraints_path=_path(source, "AIOS_CONSTRAINTS_PATH") or DEFAULT_CONSTRAINTS_PATH,
            seed=_integer(source, "AIOS_SEED", DEFAULT_SEED),
            lambda_root=lambda_root,
            lambda_path=_path(source, "AIOS_LAMBDA_PATH"),
            lambda_steps=(
                _integer(source, "AIOS_LAMBDA_STEPS", 0)
                if _text(source, "AIOS_LAMBDA_STEPS")
                else None
            ),
            lambda_workers=_integer(source, "AIOS_LAMBDA_WORKERS", DEFAULT_LAMBDA_WORKERS),
            lambda_limit=(
                _integer(source, "AIOS_LAMBDA_LIMIT", 0)
                if _text(source, "AIOS_LAMBDA_LIMIT")
                else None
            ),
            lambda_selection_path=_path(source, "AIOS_LAMBDA_SELECTION_PATH"),
            search_diagnostics_path=(
                _path(source, "AIOS_SEARCH_DIAGNOSTICS_PATH") or DEFAULT_SEARCH_DIAGNOSTICS_PATH
            ),
            search_result_path=(
                _path(source, "AIOS_SEARCH_RESULT_PATH") or DEFAULT_SEARCH_RESULT_PATH
            ),
            search_fixed_point_cap=_positive_cap(
                source, "AIOS_SEARCH_FIXED_POINT_CAP", DEFAULT_SEARCH_FIXED_POINT_CAP
            ),
            final_fixed_point_cap=_positive_cap(
                source, "AIOS_FINAL_FIXED_POINT_CAP", DEFAULT_FINAL_FIXED_POINT_CAP
            ),
            risk_aversion_beta=_real(
                source, "AIOS_RISK_AVERSION_BETA", DEFAULT_RISK_AVERSION_BETA
            ),
            compdat_model_dir=_path(source, "AIOS_COMPDAT_MODEL_DIR"),
            base_run_dir=_path(source, "AIOS_BASE_RUN_DIR"),
            opm_image=_text(source, "OPM_FLOW_IMAGE") or DEFAULT_OPM_IMAGE,
            opm_budget_journal=_path(source, "AIOS_OPM_BUDGET_JOURNAL"),
            opm_run_initiator=_text(source, "AIOS_RUN_INITIATOR"),
            jarvis_host=_text(source, "AIOS_JARVIS_HOST") or DEFAULT_JARVIS_HOST,
            jarvis_port=_integer(source, "AIOS_JARVIS_PORT", DEFAULT_JARVIS_PORT),
            jarvis_upstream=_text(source, "AIOS_JARVIS_UPSTREAM") or DEFAULT_JARVIS_UPSTREAM,
            jarvis_config=_path(source, "AIOS_JARVIS_CONFIG"),
            jarvis_docs=_path(source, "AIOS_JARVIS_DOCS"),
            jarvis_knowledge=_path(source, "AIOS_JARVIS_KNOWLEDGE"),
            jarvis_system=_path(source, "AIOS_JARVIS_SYSTEM"),
            jarvis_runs=_path(source, "AIOS_JARVIS_RUNS"),
            jarvis_sessions=_path(source, "AIOS_JARVIS_SESSIONS"),
            jarvis_web_runs=_path(source, "AIOS_JARVIS_WEB_RUNS"),
            jarvis_champion=_path(source, "AIOS_JARVIS_CHAMPION"),
            jarvis_tts_cache=_path(source, "AIOS_JARVIS_TTS_CACHE"),
            voice_ru=_text(source, "AIOS_JARVIS_VOICE_RU") or DEFAULT_VOICE_RU,
            voice_en=_text(source, "AIOS_JARVIS_VOICE_EN") or DEFAULT_VOICE_EN,
            openrouter_api_key=_text(source, "OPENROUTER_API_KEY"),
            anthropic_api_key=_text(source, "ANTHROPIC_API_KEY"),
            dashboard_password=source.get("AIOS_DASHBOARD_PASSWORD", ""),
            ui_data_root=_path(source, "AIOS_UI_DATA"),
            surrogate_bundle=_path(source, "AIOS_SURROGATE_BUNDLE"),
            surrogate_manifest=_path(source, "AIOS_SURROGATE_MANIFEST"),
            checkpoint_dir=_path(source, "AIOS_CHECKPOINT_DIR"),
            checkpoint_path=_path(source, "AIOS_CHECKPOINT_PATH"),
            dataset_root=_path(source, "AIOS_DATASET_ROOT"),
            npv_head_path=_path(source, "AIOS_NPV_HEAD_PATH"),
            npv_calibration_path=_path(source, "AIOS_NPV_CALIBRATION_PATH"),
            ood_calibration_path=_path(source, "AIOS_OOD_CALIBRATION_PATH"),
            ood_threshold=(
                _real(source, "AIOS_OOD_THRESHOLD", 0.0) if ood_threshold_raw else None
            ),
            scenario_ood_path=_path(source, "AIOS_SCENARIO_OOD_PATH"),
            feature_context_path=_path(source, "AIOS_FEATURE_CONTEXT_PATH"),
            raw=dict(source),
        )


ENV_VARIABLES: tuple[str, ...] = (
    PROJECT_ROOT_ENV_VAR,
    DATA_ROOT_ENV_VAR,
    OUT_ROOT_ENV_VAR,
    DOCS_ROOT_ENV_VAR,
    "AIOS_HORIZON_PATH",
    "AIOS_CONSTRAINTS_PATH",
    "AIOS_SEED",
    "AIOS_LAMBDA_ROOT",
    "AIOS_LAMBDA_PATH",
    "AIOS_LAMBDA_STEPS",
    "AIOS_LAMBDA_WORKERS",
    "AIOS_LAMBDA_LIMIT",
    "AIOS_LAMBDA_SELECTION_PATH",
    "AIOS_SEARCH_DIAGNOSTICS_PATH",
    "AIOS_SEARCH_RESULT_PATH",
    "AIOS_SEARCH_FIXED_POINT_CAP",
    "AIOS_FINAL_FIXED_POINT_CAP",
    "AIOS_RISK_AVERSION_BETA",
    "AIOS_COMPDAT_MODEL_DIR",
    "AIOS_BASE_RUN_DIR",
    "OPM_FLOW_IMAGE",
    "AIOS_OPM_BUDGET_JOURNAL",
    "AIOS_RUN_INITIATOR",
    "AIOS_JARVIS_HOST",
    "AIOS_JARVIS_PORT",
    "AIOS_JARVIS_UPSTREAM",
    "AIOS_JARVIS_CONFIG",
    "AIOS_JARVIS_DOCS",
    "AIOS_JARVIS_KNOWLEDGE",
    "AIOS_JARVIS_SYSTEM",
    "AIOS_JARVIS_RUNS",
    "AIOS_JARVIS_SESSIONS",
    "AIOS_JARVIS_WEB_RUNS",
    "AIOS_JARVIS_CHAMPION",
    "AIOS_JARVIS_TTS_CACHE",
    "AIOS_JARVIS_VOICE_RU",
    "AIOS_JARVIS_VOICE_EN",
    "OPENROUTER_API_KEY",
    "ANTHROPIC_API_KEY",
    "AIOS_DASHBOARD_PASSWORD",
    "AIOS_UI_DATA",
    "AIOS_SURROGATE_BUNDLE",
    "AIOS_SURROGATE_MANIFEST",
    "AIOS_CHECKPOINT_DIR",
    "AIOS_CHECKPOINT_PATH",
    "AIOS_DATASET_ROOT",
    "AIOS_NPV_HEAD_PATH",
    "AIOS_NPV_CALIBRATION_PATH",
    "AIOS_OOD_CALIBRATION_PATH",
    "AIOS_OOD_THRESHOLD",
    "AIOS_SCENARIO_OOD_PATH",
    "AIOS_FEATURE_CONTEXT_PATH",
)


__all__ = ["DEFAULT_SEED", "ENV_VARIABLES", "Settings"]
