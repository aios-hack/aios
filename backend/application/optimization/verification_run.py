from __future__ import annotations

import json
import sys
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from backend.infrastructure.opm import SubmissionResult, submit_schedule
from backend.infrastructure.opm.opm_deck import OpmDeckEmitter
from backend.infrastructure.opm.runner import deck_hashes, summary_spec_hash
from backend.domain.configuration.schema import default_config
from backend.core.contracts import ArtifactHashes, Constraints, Schedule, Theta
from backend.core.contracts.hashing import canonical_bytes, hash_schedule
from backend.domain.schedule.canonical import canonical_part_hash
from backend.domain.schedule.json_io import load_schedule_json
from backend.domain.economics import (
    load_normatives,
    load_response_artifact,
    save_response_artifact,
)
from backend.application.optimization.schedule_search import load_environment, make_evaluator, make_policy
from backend.application.optimization.runtime_artifacts import (
    resolve_runtime_artifacts,
    validate_runtime_economic_head,
)
from backend.application.optimization.search_run import (
    CONSTRAINTS,
    FINAL_CAP,
    SEED,
    _repair_predicted_water_balance,
)
from backend.domain.policy.fixed_point import resolve
from backend.domain.policy.theta import default_theta
from backend.infrastructure.resources import chdd_python_dir, model_z_dir
from backend.domain.configuration.constraints_io import (
    constraints_from_json,
    constraints_hash,
)

LAMBDA = Path("data/lambda-window-2007/lambda.json")
RESPONSE = Path("data/base_case/response.json")
WORK_ROOT = Path("data/g7-submission")
EXPECTED_HASH: str | None = None
BASE_NPV = 11_873_676_459.64
OIL_DENSITY_T_PER_M3 = 0.9131


class VerificationGuardError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class GuardCheck:
    name: str
    expected: str | None
    actual: str
    source: str

    @property
    def checked(self) -> bool:
        return self.expected is not None

    @property
    def holds(self) -> bool:
        return self.expected is not None and self.expected == self.actual

    def as_dict(self) -> dict[str, object]:
        return {
            "name": self.name,
            "checked": self.checked,
            "holds": self.holds,
            "expected": self.expected,
            "actual": self.actual,
            "source": self.source,
        }


@dataclass(frozen=True, slots=True)
class GuardReport:
    schedule: GuardCheck
    constraints: GuardCheck

    @property
    def checks(self) -> tuple[GuardCheck, ...]:
        return (self.schedule, self.constraints)

    @property
    def unchecked(self) -> tuple[GuardCheck, ...]:
        return tuple(check for check in self.checks if not check.checked)

    @property
    def fully_checked(self) -> bool:
        return not self.unchecked

    def as_dict(self) -> dict[str, object]:
        return {
            "fully_checked": self.fully_checked,
            "unchecked": [check.name for check in self.unchecked],
            "checks": [check.as_dict() for check in self.checks],
        }

    def raise_if_broken(self) -> None:
        broken = [
            check for check in self.checks if check.checked and not check.holds
        ]
        if not broken:
            return
        details = "; ".join(
            f"{check.name}: в прогоне {check.expected}, предъявлено "
            f"{check.actual} (источник эталона: {check.source})"
            for check in broken
        )
        raise VerificationGuardError(
            "верификация прекращена до запуска Flow: предъявленное к проверке "
            f"расходится с зафиксированным в прогоне — {details}"
        )


def _load_constraints() -> Constraints:
    return constraints_from_json(
        json.loads(CONSTRAINTS.read_text(encoding="utf-8"))
    )


def _read_manifest(run_dir: Path) -> dict[str, object]:
    path = run_dir / "manifest.json"
    if not path.is_file():
        return {}
    document = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(document, dict):
        raise VerificationGuardError(
            f"манифест прогона не объект JSON: {path}"
        )
    return document


def _manifest_hash(document: dict[str, object], field: str, run_dir: Path) -> str | None:
    value = document.get(field)
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        raise VerificationGuardError(
            f"манифест прогона {run_dir} содержит {field}={value!r}; "
            "эталонный хеш должен быть непустой строкой"
        )
    return value


def _run_constraints_hash(run_dir: Path) -> str | None:
    path = run_dir / "inputs" / "constraints.json"
    if not path.is_file():
        return None
    document = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(document, dict):
        raise VerificationGuardError(
            f"сохранённый кейс прогона не объект JSON: {path}"
        )
    return constraints_hash(constraints_from_json(document))


def resolve_guard_report(
    schedule: Schedule,
    constraints: Constraints,
    *,
    run_dir: Path | None = None,
    expected_schedule_hash: str | None = None,
    expected_constraints_hash: str | None = None,
) -> GuardReport:
    schedule_source = "аргумент expected_schedule_hash"
    constraints_source = "аргумент expected_constraints_hash"
    if expected_schedule_hash is None and EXPECTED_HASH is not None:
        expected_schedule_hash = EXPECTED_HASH
        schedule_source = "константа EXPECTED_HASH"
    if run_dir is not None:
        manifest = _read_manifest(run_dir)
        if expected_schedule_hash is None:
            expected_schedule_hash = _manifest_hash(
                manifest, "schedule_hash", run_dir
            )
            schedule_source = f"{run_dir / 'manifest.json'}:schedule_hash"
        if expected_constraints_hash is None:
            expected_constraints_hash = _manifest_hash(
                manifest, "constraints_hash", run_dir
            )
            constraints_source = f"{run_dir / 'manifest.json'}:constraints_hash"
        if expected_constraints_hash is None:
            expected_constraints_hash = _run_constraints_hash(run_dir)
            constraints_source = str(run_dir / "inputs" / "constraints.json")
    if expected_schedule_hash is None:
        schedule_source = "эталон не найден"
    if expected_constraints_hash is None:
        constraints_source = "эталон не найден"
    return GuardReport(
        schedule=GuardCheck(
            name="canonical_schedule_hash",
            expected=expected_schedule_hash,
            actual=hash_schedule(schedule),
            source=schedule_source,
        ),
        constraints=GuardCheck(
            name="constraints_hash",
            expected=expected_constraints_hash,
            actual=constraints_hash(constraints),
            source=constraints_source,
        ),
    )


def _guard_run_dir(work_root: Path, run_dir: Path | None) -> Path | None:
    if run_dir is not None:
        return run_dir
    candidate = work_root.parent
    if (candidate / "manifest.json").is_file() or (
        candidate / "inputs" / "constraints.json"
    ).is_file():
        return candidate
    return None


@dataclass(frozen=True, slots=True)
class GuardedVerification:
    result: SubmissionResult
    guard: GuardReport


def verify_schedule_with_guard(
    schedule: Schedule,
    work_root: Path,
    *,
    run_dir: Path | None = None,
    expected_schedule_hash: str | None = None,
    expected_constraints_hash: str | None = None,
    constraints: Constraints | None = None,
) -> GuardedVerification:
    used_constraints = constraints if constraints is not None else _load_constraints()
    guard = resolve_guard_report(
        schedule,
        used_constraints,
        run_dir=_guard_run_dir(work_root, run_dir),
        expected_schedule_hash=expected_schedule_hash,
        expected_constraints_hash=expected_constraints_hash,
    )
    work_root.mkdir(parents=True, exist_ok=True)
    (work_root / "verification-guard.json").write_text(
        json.dumps(guard.as_dict(), ensure_ascii=False, indent=2, sort_keys=True)
        + "\n",
        encoding="utf-8",
    )
    guard.raise_if_broken()
    for check in guard.unchecked:
        print(
            f"ВНИМАНИЕ: {check.name} не сверяется — эталон отсутствует, "
            f"фактическое значение {check.actual}",
            flush=True,
        )
    model_dir = model_z_dir()
    normatives_path = chdd_python_dir() / "input" / "Нормативы_ЧДД.xlsx"
    normatives = load_normatives(normatives_path)
    emitter = OpmDeckEmitter(model_dir)
    with tempfile.TemporaryDirectory() as scratch:
        deck = emitter.emit(schedule, Path(scratch) / "deck")
        hashes = deck_hashes(deck, schedule)
        summary_hash = summary_spec_hash(deck.summary_plan.spec)
    config = default_config(
        normatives,
        ArtifactHashes(
            deck_hash=hashes.deck_hash,
            history_prefix_hash=canonical_part_hash(schedule.initial_state),
            summary_spec_hash=summary_hash,
            groups_hash="0" * 64,
            dataset_version_hash="0" * 64,
            surrogate_checkpoint_hash="0" * 64,
        ),
        global_seed=SEED,
    )
    result = submit_schedule(
        schedule,
        model_dir,
        work_root,
        config,
        constraints=used_constraints,
        strict=False,
        oil_density_t_per_m3=OIL_DENSITY_T_PER_M3,
    )
    return GuardedVerification(result=result, guard=guard)


def verify_schedule(
    schedule: Schedule,
    work_root: Path,
    *,
    run_dir: Path | None = None,
    expected_schedule_hash: str | None = None,
    expected_constraints_hash: str | None = None,
    constraints: Constraints | None = None,
) -> SubmissionResult:
    return verify_schedule_with_guard(
        schedule,
        work_root,
        run_dir=run_dir,
        expected_schedule_hash=expected_schedule_hash,
        expected_constraints_hash=expected_constraints_hash,
        constraints=constraints,
    ).result


def persist_observation(
    schedule: Schedule,
    result: SubmissionResult,
    *,
    predicted_npv: float | None,
    observation_root: Path = Path("data/opm-observations"),
    metadata: dict[str, object] | None = None,
    guard: GuardReport | None = None,
) -> Path:
    schedule_hash = hash_schedule(schedule)
    observation_dir = observation_root / schedule_hash
    observation_dir.mkdir(parents=True, exist_ok=True)
    (observation_dir / "schedule.json").write_bytes(canonical_bytes(schedule))
    if result.response is not None:
        save_response_artifact(result.response, observation_dir / "response.json")
    if result.dynamic_report is not None:
        (observation_dir / "dynamic-report.json").write_bytes(
            canonical_bytes(result.dynamic_report)
        )
    final_summary = None
    if result.final_npv is not None:
        final_summary = {
            "npv_methodology": result.final_npv.npv_methodology,
            "source_run_id": result.final_npv.source_run_id,
            "source_response_hash": result.final_npv.source_response_hash,
            "economics_config_hash": result.final_npv.economics_config_hash,
            "methodology_version_hash": result.final_npv.methodology_version_hash,
        }
        (observation_dir / "final-npv-summary.json").write_text(
            json.dumps(final_summary, ensure_ascii=False, indent=2, sort_keys=True),
            encoding="utf-8",
        )
    (observation_dir / "observation.json").write_text(
        json.dumps(
            {
                "canonical_schedule_hash": schedule_hash,
                "run_id": result.opm_run.run_id,
                "run_status": str(result.opm_run.status),
                "sound": result.sound,
                "predicted_npv": predicted_npv,
                "opm_npv": final_summary["npv_methodology"] if final_summary else None,
                "dynamic_violations": (
                    len(result.dynamic_report.violations)
                    if result.dynamic_report is not None
                    else None
                ),
                "verification_guard": guard.as_dict() if guard is not None else None,
                "metadata": metadata or {},
            },
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    return observation_dir


def main() -> int:
    model_dir = model_z_dir()
    normatives_path = chdd_python_dir() / "input" / "Нормативы_ЧДД.xlsx"
    runtime = resolve_runtime_artifacts()
    constraints = _load_constraints()
    env = load_environment(
        model_dir=model_dir,
        normatives_path=normatives_path,
        response_path=RESPONSE,
        checkpoint_path=runtime.checkpoint,
        feature_context_path=runtime.feature_context,
        npv_head_path=runtime.npv_head,
        lambda_path=LAMBDA,
        constraints=constraints,
        oil_density_t_per_m3=OIL_DENSITY_T_PER_M3,
    )
    validate_runtime_economic_head(runtime, env.npv_head)
    initial = load_response_artifact(RESPONSE)
    evaluator = make_evaluator(env)

    saved = json.loads(Path("data/lambda-window-2007/cmaes.json").read_text(encoding="utf-8"))
    if saved.get('schedule_path'):
        schedule = load_schedule_json(Path(saved['schedule_path']))
        repaired_prediction = evaluator(schedule)
        repair_rounds = 0
        actual_hash = hash_schedule(schedule)
        print('Проверяется сохранённый план без повторной генерации политики.', flush=True)
    else:
        theta = Theta(values=dict(saved["theta"]), bounds=default_theta().bounds)
        started = time.monotonic()
        final = resolve(make_policy(env, theta, {}), evaluator, initial, FINAL_CAP)
        schedule, repaired_prediction, _dynamic, repair_rounds = _repair_predicted_water_balance(
            env, evaluator, final.schedule
        )
        actual_hash = hash_schedule(schedule)
        print(
            f"план восстановлен из θ* за {time.monotonic() - started:.1f} с, "
            f"предсказание economic head {final.npv / 1e9:.3f} млрд, "
            f"policy-stable={final.self_consistent}, water-repair={repair_rounds}",
            flush=True,
        )
    print(f"canonical_schedule_hash: {actual_hash}", flush=True)
    expected = EXPECTED_HASH or saved["canonical_schedule_hash"]
    if actual_hash != expected:
        print(f"ХЕШ РАЗОШЁЛСЯ с записанным {expected}", flush=True)
        return 3
    print("хеш совпал с записанным в cmaes.json", flush=True)

    print("\nзвено А: эмит, прогон Flow, отклик, гейт, экономика...", flush=True)
    started = time.monotonic()
    try:
        guarded = verify_schedule_with_guard(
            schedule,
            WORK_ROOT,
            expected_schedule_hash=expected,
            constraints=constraints,
        )
    except VerificationGuardError as error:
        print(f"\n{error}", flush=True)
        return 3
    result = guarded.result
    guard = guarded.guard
    print(f"тракт отработал за {(time.monotonic() - started) / 60:.1f} мин", flush=True)

    print(f"\nстатус прогона: {result.opm_run.status}", flush=True)
    print(f"годен к сдаче (sound): {result.sound}", flush=True)
    for check in result.identities:
        mark = "OK " if check.holds else "НЕТ"
        print(f"  [{mark}] {check.name}", flush=True)
        if not check.holds:
            print(f"        {check.detail}", flush=True)
    if result.dynamic_report is not None:
        counts = {}
        for violation in result.dynamic_report.violations:
            counts[violation.kind] = counts.get(violation.kind, 0) + 1
        print(f"\nvalidate_dynamic: {len(result.dynamic_report.violations)} нарушений", flush=True)
        for kind, count in sorted(counts.items(), key=lambda item: -item[1]):
            print(f"  {kind}: {count}", flush=True)
    if result.final_npv is not None:
        npv = result.final_npv.npv_methodology
        surrogate_npv = repaired_prediction.npv
        print(
            f"\nЧДД по настоящему прогону: {npv / 1e9:.3f} млрд "
            f"({100.0 * (npv - BASE_NPV) / BASE_NPV:+.1f}% к базовому), "
            f"предсказание economic head было {surrogate_npv / 1e9:.3f} млрд "
            f"(ошибка {100.0 * (surrogate_npv - npv) / npv:+.1f}%)",
            flush=True,
        )
    persist_observation(
        schedule,
        result,
        predicted_npv=repaired_prediction.npv,
        metadata={"candidate": "cmaes-policy", "water_repair_rounds": repair_rounds},
        guard=guard,
    )
    Path("data/g7-result.json").write_text(
        json.dumps(
            {
                "canonical_schedule_hash": actual_hash,
                "run_status": str(result.opm_run.status),
                "sound": result.sound,
                "failed_identities": [c.name for c in result.failed_identities],
                "npv_surrogate": repaired_prediction.npv,
                "npv_opm": result.final_npv.npv_methodology if result.final_npv else None,
                "npv_baseline": BASE_NPV,
                "dynamic_violations": len(result.dynamic_report.violations)
                if result.dynamic_report
                else None,
                "verification_guard": guard.as_dict() if guard is not None else None,
            },
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    print("\nитог записан: data/g7-result.json", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
