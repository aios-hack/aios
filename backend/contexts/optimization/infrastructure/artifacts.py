from __future__ import annotations

import json
import hashlib
import math
import os
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from backend.shared.paths import project_root


class RuntimeArtifactError(ValueError):
    pass


CONSERVATIVE_OOD_THRESHOLD = 0.0
OOD_CALIBRATION_FORMAT = "aios.ood-calibration.v1"
DEFAULT_OOD_CALIBRATION = "out/ood-calibration.json"


@dataclass(frozen=True, slots=True)
class OodThresholdDecision:
    value: float
    origin: str
    calibrated: bool
    calibration_path: Path | None
    point_count: int
    detail: str

    def as_provenance(self) -> dict[str, str]:
        return {
            "ood_threshold": repr(self.value),
            "ood_threshold_origin": self.origin,
            "ood_threshold_calibrated": "true" if self.calibrated else "false",
            "ood_threshold_source": (
                "none" if self.calibration_path is None else str(self.calibration_path)
            ),
            "ood_threshold_point_count": str(self.point_count),
            "ood_threshold_detail": self.detail,
        }


def _parse_threshold_override(raw: str) -> float:
    try:
        value = float(raw)
    except ValueError as error:
        raise RuntimeArtifactError(
            f"AIOS_OOD_THRESHOLD={raw!r} — порог области применимости задаётся числом"
        ) from error
    if not math.isfinite(value) or value < 0.0:
        raise RuntimeArtifactError(
            f"AIOS_OOD_THRESHOLD={raw!r} — порог обязан быть конечным и неотрицательным"
        )
    return value


def _read_calibration(path: Path) -> tuple[float, int, bool]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise RuntimeArtifactError(
            f"артефакт калибровки OOD {path} не читается: {error}"
        ) from error
    if not isinstance(payload, dict) or payload.get("format") != OOD_CALIBRATION_FORMAT:
        raise RuntimeArtifactError(f"неподдерживаемый артефакт калибровки OOD: {path}")
    threshold = payload.get("threshold")
    if not isinstance(threshold, (int, float)) or isinstance(threshold, bool):
        raise RuntimeArtifactError(f"{path}: порог калибровки не число")
    value = float(threshold)
    if not math.isfinite(value) or value < 0.0:
        raise RuntimeArtifactError(
            f"{path}: порог калибровки {value} не конечен или отрицателен"
        )
    count = payload.get("point_count")
    if not isinstance(count, int) or isinstance(count, bool) or count < 1:
        raise RuntimeArtifactError(
            f"{path}: калибровка без единой измеренной точки не задаёт порог"
        )
    return value, count, bool(payload.get("curve_is_reliable", False))


def resolve_ood_threshold(
    environ: Mapping[str, str] | None = None,
) -> OodThresholdDecision:
    env = os.environ if environ is None else environ
    override = env.get("AIOS_OOD_THRESHOLD")
    configured = env.get("AIOS_OOD_CALIBRATION_PATH")
    root_override = env.get("AIOS_PROJECT_ROOT")
    root = Path(root_override).expanduser().resolve() if root_override else project_root()
    calibration_path = (
        Path(configured) if configured else root / DEFAULT_OOD_CALIBRATION
    )
    if override is not None:
        value = _parse_threshold_override(override)
        return OodThresholdDecision(
            value=value,
            origin="environment-override",
            calibrated=False,
            calibration_path=calibration_path if calibration_path.is_file() else None,
            point_count=0,
            detail=(
                f"AIOS_OOD_THRESHOLD={override!r} перекрывает артефакт калибровки; "
                "происхождение порога — явное переопределение оператором"
            ),
        )
    if configured and not calibration_path.is_file():
        raise RuntimeArtifactError(
            f"AIOS_OOD_CALIBRATION_PATH={configured} указывает на отсутствующий "
            "артефакт калибровки"
        )
    if not calibration_path.is_file():
        return OodThresholdDecision(
            value=CONSERVATIVE_OOD_THRESHOLD,
            origin="uncalibrated-conservative-default",
            calibrated=False,
            calibration_path=None,
            point_count=0,
            detail=(
                f"артефакт калибровки {calibration_path} отсутствует: порог "
                f"{CONSERVATIVE_OOD_THRESHOLD} взят как консервативный, "
                "НЕ ОТКАЛИБРОВАН — отвергается любой кандидат хоть с одним "
                "узлом вне обучающего диапазона"
            ),
        )
    value, count, reliable = _read_calibration(calibration_path)
    return OodThresholdDecision(
        value=value,
        origin=(
            "calibration-artifact"
            if reliable
            else "calibration-artifact/insufficient-points"
        ),
        calibrated=True,
        calibration_path=calibration_path,
        point_count=count,
        detail=(
            f"порог {value} взят из {calibration_path} по {count} измеренным "
            f"точкам «ошибка против OOD»"
            + ("" if reliable else "; точек мало, кривая ненадёжна")
        ),
    )


LAMBDA_SELECTION_FORMAT = "aios.lambda-selection.v1"
DEFAULT_LAMBDA_SELECTION = "config/lambda-selection.json"
LAMBDA_PATH_ENV = "AIOS_LAMBDA_PATH"
LAMBDA_SELECTION_ENV = "AIOS_LAMBDA_SELECTION_PATH"


@dataclass(frozen=True, slots=True)
class LambdaSelection:
    path: Path
    name: str
    origin: str
    selection_path: Path | None
    rationale: str
    expected_feature_context_sha256: str | None
    feature_context_match: str

    def as_provenance(self) -> dict[str, str]:
        return {
            "lambda_path": str(self.path),
            "lambda_selection": self.name,
            "lambda_selection_origin": self.origin,
            "lambda_selection_source": (
                "none" if self.selection_path is None else str(self.selection_path)
            ),
            "lambda_selection_rationale": self.rationale,
            "lambda_expected_feature_context_sha256": (
                self.expected_feature_context_sha256 or "unrecorded"
            ),
            "lambda_feature_context_match": self.feature_context_match,
        }


def _read_lambda_selection_document(path: Path) -> dict[str, object]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise RuntimeArtifactError(
            f"конфигурация выбора λ {path} не читается: {error}"
        ) from error
    if not isinstance(payload, dict):
        raise RuntimeArtifactError(
            f"{path}: конфигурация выбора λ не является объектом"
        )
    if payload.get("format") != LAMBDA_SELECTION_FORMAT:
        raise RuntimeArtifactError(
            f"неподдерживаемый формат конфигурации выбора λ {path}: "
            f"{payload.get('format')!r}"
        )
    return payload


def _lambda_candidate(
    path: Path, payload: Mapping[str, object]
) -> tuple[str, Mapping[str, object]]:
    selected = payload.get("selected")
    if not isinstance(selected, str) or not selected:
        raise RuntimeArtifactError(
            f"{path}: поле selected не называет ни одного кандидата λ — выбор "
            "обязан быть записан явно, а не подставлен умолчанием"
        )
    candidates = payload.get("candidates")
    if not isinstance(candidates, dict) or not candidates:
        raise RuntimeArtifactError(
            f"{path}: раздел candidates пуст, выбирать не из чего"
        )
    candidate = candidates.get(selected)
    if not isinstance(candidate, dict):
        raise RuntimeArtifactError(
            f"{path}: выбран кандидат λ {selected!r}, которого нет в candidates"
        )
    return selected, candidate


def _lambda_rationale(path: Path, name: str, candidate: Mapping[str, object]) -> str:
    rationale = candidate.get("rationale")
    if not isinstance(rationale, str) or not rationale.strip():
        raise RuntimeArtifactError(
            f"{path}: кандидат λ {name!r} записан без обоснования — выбор без "
            "причины неотличим от умолчания, а провенанс обязан её нести"
        )
    return rationale.strip()


def _lambda_feature_context_match(
    expected: str | None, feature_context: Path | None
) -> str:
    if expected is None:
        return "unrecorded"
    if feature_context is None:
        return "not-checked"
    if not feature_context.is_file():
        raise RuntimeArtifactError(
            f"контекст признаков {feature_context} не читается: сверить λ с "
            "признаками модели нечем"
        )
    actual = hashlib.sha256(feature_context.read_bytes()).hexdigest()
    if actual != expected:
        raise RuntimeArtifactError(
            f"λ выбрана как выгрузка из контекста признаков с "
            f"feature_context_sha256={expected}, а производственный контекст "
            f"{feature_context} имеет {actual}: связность поиска и признаки "
            "модели разошлись, и результат поиска относился бы к другой матрице"
        )
    return "identical"


def resolve_lambda_selection(
    environ: Mapping[str, str] | None = None,
    feature_context: Path | None = None,
) -> LambdaSelection:
    env = os.environ if environ is None else environ
    root_override = env.get("AIOS_PROJECT_ROOT")
    root = Path(root_override).expanduser().resolve() if root_override else project_root()
    configured = env.get(LAMBDA_SELECTION_ENV)
    selection_path = Path(configured) if configured else root / DEFAULT_LAMBDA_SELECTION
    override = env.get(LAMBDA_PATH_ENV)
    if override:
        return LambdaSelection(
            path=Path(override),
            name="environment-override",
            origin="environment-override",
            selection_path=selection_path if selection_path.is_file() else None,
            rationale=(
                f"{LAMBDA_PATH_ENV}={override!r} перекрывает конфигурацию выбора "
                "λ: происхождение матрицы — явное решение оператора, а не запись "
                "в конфигурации, и сверка с контекстом признаков не выполнялась"
            ),
            expected_feature_context_sha256=None,
            feature_context_match="not-checked",
        )
    if configured and not selection_path.is_file():
        raise RuntimeArtifactError(
            f"{LAMBDA_SELECTION_ENV}={configured} указывает на отсутствующую "
            "конфигурацию выбора λ"
        )
    if not selection_path.is_file():
        raise RuntimeArtifactError(
            f"конфигурации выбора λ нет по пути {selection_path}: путь к матрице "
            "связности задаётся конфигурацией, и подставлять его константой "
            "модуля запрещено — поиск оптимизировал бы по неизвестно какой λ"
        )
    payload = _read_lambda_selection_document(selection_path)
    name, candidate = _lambda_candidate(selection_path, payload)
    raw_path = candidate.get("path")
    if not isinstance(raw_path, str) or not raw_path:
        raise RuntimeArtifactError(
            f"{selection_path}: кандидат λ {name!r} записан без пути к артефакту"
        )
    lambda_path = Path(raw_path)
    if not lambda_path.is_absolute():
        lambda_path = root / lambda_path
    if not lambda_path.is_file():
        raise RuntimeArtifactError(
            f"{selection_path}: выбранная λ {name!r} отсутствует по пути "
            f"{lambda_path}"
        )
    rationale = _lambda_rationale(selection_path, name, candidate)
    raw_expected = candidate.get("expected_feature_context_sha256")
    expected: str | None = None
    if raw_expected is not None:
        if not isinstance(raw_expected, str) or len(raw_expected) != 64:
            raise RuntimeArtifactError(
                f"{selection_path}: кандидат λ {name!r} объявил "
                "expected_feature_context_sha256, не являющийся SHA-256"
            )
        expected = raw_expected.lower()
    match = _lambda_feature_context_match(expected, feature_context)
    return LambdaSelection(
        path=lambda_path,
        name=name,
        origin="selection-config",
        selection_path=selection_path,
        rationale=rationale,
        expected_feature_context_sha256=expected,
        feature_context_match=match,
    )


RELEASE_FORMAT = "aios.surrogate-release.v1"
RELEASE_FILENAME = "release.json"
INSTALL_MANIFEST_FORMAT = "aios.surrogate-runtime.v1"


@dataclass(frozen=True, slots=True)
class FileVerdict:
    path: str
    expected_sha256: str
    actual_sha256: str | None
    status: str

    @property
    def ok(self) -> bool:
        return self.status == "ok"

    def as_dict(self) -> dict[str, str | None]:
        return {
            "path": self.path,
            "status": self.status,
            "expected_sha256": self.expected_sha256,
            "actual_sha256": self.actual_sha256,
        }


@dataclass(frozen=True, slots=True)
class BundleVerdict:
    root: Path
    reference: Path
    reference_format: str
    files: tuple[FileVerdict, ...]
    extra_files: tuple[str, ...]

    @property
    def mismatched(self) -> tuple[FileVerdict, ...]:
        return tuple(item for item in self.files if not item.ok)

    @property
    def ok(self) -> bool:
        return not self.mismatched

    @property
    def exit_code(self) -> int:
        return 0 if self.ok else 1

    def as_dict(self) -> dict[str, object]:
        return {
            "format": "aios.surrogate-bundle-verdict.v1",
            "root": str(self.root),
            "reference": str(self.reference),
            "reference_format": self.reference_format,
            "checked_file_count": len(self.files),
            "mismatched_file_count": len(self.mismatched),
            "status": "ok" if self.ok else "corrupted",
            "files": [item.as_dict() for item in self.files],
            "mismatches": [item.as_dict() for item in self.mismatched],
            "extra_files": list(self.extra_files),
        }


def _read_expected_checksums(reference: Path) -> tuple[dict[str, str], str]:
    try:
        payload = json.loads(reference.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise RuntimeArtifactError(
            f"опись пакета {reference} не читается: {error}"
        ) from error
    if not isinstance(payload, dict):
        raise RuntimeArtifactError(f"опись пакета {reference} не является объектом")
    declared = payload.get("format")
    if declared not in {RELEASE_FORMAT, INSTALL_MANIFEST_FORMAT}:
        raise RuntimeArtifactError(
            f"неподдерживаемый формат описи пакета {reference}: {declared!r}"
        )
    checksums = payload.get("files_sha256")
    if not isinstance(checksums, dict) or not checksums:
        raise RuntimeArtifactError(
            f"{reference}: опись без files_sha256 не задаёт ни одной контрольной "
            "суммы — сверять нечего, а молчаливый успех означал бы непроверенный пакет"
        )
    expected: dict[str, str] = {}
    for name, digest in checksums.items():
        if not isinstance(name, str) or not isinstance(digest, str) or len(digest) != 64:
            raise RuntimeArtifactError(
                f"{reference}: запись описи {name!r} не является парой "
                "«путь — SHA-256»"
            )
        expected[name] = digest.lower()
    return expected, str(declared)


def _bundle_reference(root: Path) -> Path:
    release = root / RELEASE_FILENAME
    if release.is_file():
        return release
    raise RuntimeArtifactError(
        f"в пакете {root} нет {RELEASE_FILENAME}: без описи с контрольными "
        "суммами вердикт о целостности вынести нельзя"
    )


def verify_bundle(root: Path | str, reference: Path | str | None = None) -> BundleVerdict:
    bundle_root = Path(root).resolve()
    if not bundle_root.is_dir():
        raise RuntimeArtifactError(f"пакет {bundle_root} не является каталогом")
    reference_path = (
        _bundle_reference(bundle_root) if reference is None else Path(reference).resolve()
    )
    if not reference_path.is_file():
        raise RuntimeArtifactError(f"описи пакета нет по пути {reference_path}")
    expected, reference_format = _read_expected_checksums(reference_path)
    verdicts: list[FileVerdict] = []
    for name in sorted(expected):
        relative = Path(name)
        if relative.is_absolute() or ".." in relative.parts:
            raise RuntimeArtifactError(
                f"{reference_path}: запись описи {name!r} выводит за пределы пакета"
            )
        target = bundle_root / relative
        if not target.is_file():
            verdicts.append(FileVerdict(name, expected[name], None, "missing"))
            continue
        actual = hashlib.sha256(target.read_bytes()).hexdigest()
        status = "ok" if actual == expected[name] else "checksum-mismatch"
        verdicts.append(FileVerdict(name, expected[name], actual, status))
    known = {(bundle_root / Path(name)).resolve() for name in expected}
    known.add(reference_path)
    extra = tuple(
        sorted(
            path.relative_to(bundle_root).as_posix()
            for path in bundle_root.rglob("*")
            if path.is_file() and path.resolve() not in known
        )
    )
    return BundleVerdict(
        root=bundle_root,
        reference=reference_path,
        reference_format=reference_format,
        files=tuple(verdicts),
        extra_files=extra,
    )


@dataclass(frozen=True, slots=True)
class RuntimeArtifacts:
    checkpoint: Path
    feature_context: Path
    npv_head: Path | None
    source: str
    scenario_ood: Path | None = None
    economic_model_version: str | None = None
    economic_target_provenance_hash: str | None = None
    npv_calibration: Path | None = None


def validate_npv_scoring_is_unambiguous(artifacts: RuntimeArtifacts) -> None:
    if artifacts.npv_calibration is None or artifacts.npv_head is None:
        return
    raise RuntimeArtifactError(
        "одновременно заданы аффинная калибровка ЧДД "
        f"({artifacts.npv_calibration}) и голова прямого прогноза "
        f"({artifacts.npv_head}): калибровка подобрана на сыром физическом "
        "ЧДД и к бленду головы неприменима, поэтому итоговое число было бы "
        "посчитано не тем, чем заявлено; оставьте один механизм — уберите "
        "AIOS_NPV_CALIBRATION_PATH или AIOS_NPV_HEAD_PATH"
    )


def validate_runtime_economic_head(
    artifacts: RuntimeArtifacts, head: object | None
) -> None:
    if artifacts.economic_model_version is None:
        return
    if head is None:
        raise RuntimeArtifactError("production manifest requires an economic head")
    if getattr(head, "version", None) != artifacts.economic_model_version:
        raise RuntimeArtifactError("economic head version differs from production manifest")
    expected_target = artifacts.economic_target_provenance_hash or ""
    if getattr(head, "target_provenance_hash", "") != expected_target:
        raise RuntimeArtifactError(
            "economic target provenance differs from production manifest"
        )


def _feature_next_to_checkpoint(checkpoint: Path) -> Path:
    adjacent = checkpoint.parent / "feature_context.json"
    if adjacent.is_file():
        return adjacent
    return checkpoint.parent.parent / "feature_context.json"


def _read_pointer(manifest: Path) -> dict:
    try:
        payload = json.loads(manifest.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise RuntimeArtifactError(f"invalid production manifest {manifest}: {error}") from error
    if payload.get("format") != "aios.surrogate-production-pointer.v1":
        raise RuntimeArtifactError(f"unsupported production manifest: {manifest}")
    return payload


def resolve_runtime_artifacts(
    environ: Mapping[str, str] | None = None,
) -> RuntimeArtifacts:
    env = os.environ if environ is None else environ
    explicit_checkpoint = env.get("AIOS_CHECKPOINT_PATH")
    explicit_context = env.get("AIOS_FEATURE_CONTEXT_PATH")
    explicit_head = env.get("AIOS_NPV_HEAD_PATH")
    explicit_calibration = env.get("AIOS_NPV_CALIBRATION_PATH")
    manifest_value = env.get("AIOS_SURROGATE_MANIFEST")
    bundle_value = env.get("AIOS_SURROGATE_BUNDLE")
    legacy_dir = env.get("AIOS_CHECKPOINT_DIR")
    default_bundle = project_root() / "data" / "model-production"
    default_manifest = project_root() / "data" / "surrogate-production.json"
    economic_model_version: str | None = None
    economic_target_provenance_hash: str | None = None

    payload = {}
    scenario_ood = None

    if explicit_checkpoint:
        checkpoint = Path(explicit_checkpoint)
        context = Path(explicit_context) if explicit_context else _feature_next_to_checkpoint(checkpoint)
        head = Path(explicit_head) if explicit_head else checkpoint.parent / "npv_head.pt"
        source = "explicit checkpoint"
    elif manifest_value or default_manifest.is_file():
        manifest = Path(manifest_value) if manifest_value else default_manifest
        payload = _read_pointer(manifest)
        checkpoint = manifest.parent / payload["trajectory_checkpoint"]
        context = manifest.parent / payload["feature_context"]
        head = Path(explicit_head) if explicit_head else manifest.parent / payload["npv_head"]
        if not explicit_head:
            economic_model_version = payload.get("active_economic_model_version")
            economic_target_provenance_hash = payload.get(
                "active_economic_target_provenance_hash", ""
            )
        source = f"production manifest {manifest}"
    elif bundle_value:
        bundle = Path(bundle_value)
        checkpoint = bundle / "physical" / "trajectory_ensemble.json"
        context = Path(explicit_context) if explicit_context else bundle / "feature_context.json"
        head = Path(explicit_head) if explicit_head else bundle / "physical" / "npv_head.pt"
        source = "AIOS_SURROGATE_BUNDLE"
    elif legacy_dir:
        directory = Path(legacy_dir)
        ensemble = directory / "trajectory_ensemble.json"
        checkpoint = ensemble if ensemble.is_file() else directory / "model.pt"
        context = Path(explicit_context) if explicit_context else directory / "feature_context.json"
        head = Path(explicit_head) if explicit_head else directory / "npv_head.pt"
        source = "legacy AIOS_CHECKPOINT_DIR"
    else:
        checkpoint = default_bundle / "physical" / "trajectory_ensemble.json"
        context = default_bundle / "feature_context.json"
        head = Path(explicit_head) if explicit_head else default_bundle / "physical" / "npv_head.pt"
        source = "default production bundle"

    if source.startswith("production manifest"):
        guard = payload.get("scenario_ood")
        if not isinstance(guard, dict) or not guard.get("path") or not guard.get("sha256"):
            raise RuntimeArtifactError("production manifest requires a versioned scenario_ood artifact")
        scenario_ood = manifest.parent / guard["path"]
        if not scenario_ood.is_file():
            raise RuntimeArtifactError(f"missing runtime artifact: {scenario_ood}")
        if hashlib.sha256(scenario_ood.read_bytes()).hexdigest() != guard["sha256"]:
            raise RuntimeArtifactError("scenario OOD checksum differs from production manifest")
        if not context.is_file() or hashlib.sha256(context.read_bytes()).hexdigest() != guard.get("feature_context_sha256"):
            raise RuntimeArtifactError("scenario OOD feature context differs from production manifest")
    elif env.get("AIOS_SCENARIO_OOD_PATH"):
        scenario_ood = Path(env["AIOS_SCENARIO_OOD_PATH"])

    calibration: Path | None = None
    if explicit_calibration:
        calibration = Path(explicit_calibration)
    elif payload.get("npv_calibration"):
        calibration = manifest.parent / payload["npv_calibration"]

    required = (checkpoint, context) + ((scenario_ood,) if scenario_ood is not None else ())
    missing = [str(path) for path in required if not path.is_file()]
    if head is not None and not head.is_file():
        if explicit_head or manifest_value or source.startswith("production manifest"):
            missing.append(str(head))
        else:
            head = None
    if calibration is not None and not calibration.is_file():
        missing.append(str(calibration))
    if missing:
        raise RuntimeArtifactError(
            f"{source}: missing runtime artifact(s): {', '.join(missing)}"
        )
    artifacts = RuntimeArtifacts(
        checkpoint=checkpoint,
        feature_context=context,
        npv_head=head,
        source=source,
        scenario_ood=scenario_ood,
        economic_model_version=economic_model_version,
        economic_target_provenance_hash=economic_target_provenance_hash,
        npv_calibration=calibration,
    )
    validate_npv_scoring_is_unambiguous(artifacts)
    return artifacts
