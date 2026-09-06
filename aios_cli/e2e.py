"""One fail-closed command from a case to an OPM-verified submission."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

from optimizer.runtime_artifacts import resolve_runtime_artifacts
from ui.scenarios import load_constraints_file

from .paths import default_seed, model_z_dir, normatives_xlsx


def _default_path(env_name: str, fallback: str) -> Path:
    return Path(os.environ.get(env_name, fallback))


def build_parser() -> argparse.ArgumentParser:
    discovered_model = model_z_dir()
    discovered_normatives = normatives_xlsx()
    parser = argparse.ArgumentParser(
        prog="aios e2e",
        description=(
            "Constraints + production surrogate -> CMA-ES schedule -> OPM Flow "
            "-> dynamic gates -> methodology NPV -> submission artifacts."
        ),
    )
    parser.add_argument(
        "--model-dir",
        type=Path,
        default=_default_path(
            "AIOS_MODEL_DIR",
            str(discovered_model or Path("../docs-src/models/Model_Z")),
        ),
    )
    parser.add_argument(
        "--normatives",
        type=Path,
        default=_default_path(
            "AIOS_NORMATIVES_PATH",
            str(
                discovered_normatives
                or Path("../docs-src/models/CHDD_PYTHON/input/Нормативы_ЧДД.xlsx")
            ),
        ),
    )
    parser.add_argument(
        "--response",
        type=Path,
        default=_default_path("AIOS_RESPONSE_PATH", "data/base_case/response.json"),
    )
    parser.add_argument(
        "--lambda-path",
        type=Path,
        default=_default_path(
            "AIOS_LAMBDA_PATH", "data/lambda-window-2007/lambda.json"
        ),
    )
    parser.add_argument(
        "--constraints",
        type=Path,
        default=_default_path(
            "AIOS_CONSTRAINTS_PATH", "config/competition-constraints.json"
        ),
    )
    surrogate = parser.add_mutually_exclusive_group()
    surrogate.add_argument(
        "--surrogate-bundle",
        type=Path,
        default=(
            Path(os.environ["AIOS_SURROGATE_BUNDLE"])
            if os.environ.get("AIOS_SURROGATE_BUNDLE")
            else None
        ),
        help="Bundle containing physical/trajectory_ensemble.json and NPV head.",
    )
    surrogate.add_argument(
        "--surrogate-manifest",
        type=Path,
        default=(
            Path(os.environ["AIOS_SURROGATE_MANIFEST"])
            if os.environ.get("AIOS_SURROGATE_MANIFEST")
            else None
        ),
        help="Fail-closed aios.surrogate-production-pointer.v1 manifest.",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=_default_path("AIOS_OUT_DIR", "out/e2e"),
    )
    parser.add_argument("--budget", type=int, default=120)
    parser.add_argument("--seed", type=int, default=default_seed())
    parser.add_argument("--ood-threshold", type=float, default=0.0)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--search-only", action="store_true", help="Stop before the real OPM run."
    )
    mode.add_argument(
        "--verify-only",
        action="store_true",
        help="Use an existing out/cmaes.json and run only OPM verification.",
    )
    return parser


def _require_file(path: Path, label: str) -> Path:
    resolved = path.resolve()
    if not resolved.is_file():
        raise SystemExit(f"{label} не найден: {resolved}")
    return resolved


def _require_dir(path: Path, label: str) -> Path:
    resolved = path.resolve()
    if not resolved.is_dir():
        raise SystemExit(f"{label} не найден: {resolved}")
    return resolved


def _runtime_environment(args: argparse.Namespace) -> tuple[dict[str, str], Path]:
    if args.budget < 10:
        raise SystemExit(
            "--budget должен быть не меньше 10: одно поколение CMA-ES "
            "оценивает 10 параметров"
        )
    if args.ood_threshold < 0.0:
        raise SystemExit("--ood-threshold не может быть отрицательным")

    model = _require_dir(args.model_dir, "каталог модели")
    normatives = _require_file(args.normatives, "нормативы ЧДД")
    response = _require_file(args.response, "базовый отклик")
    lambda_path = _require_file(args.lambda_path, "измеренная lambda")
    constraints = _require_file(args.constraints, "constraints тестового кейса")
    load_constraints_file(constraints, require_water_supply=True)

    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    env = dict(os.environ)
    env.update(
        {
            "AIOS_MODEL_DIR": str(model),
            "AIOS_NORMATIVES_PATH": str(normatives),
            "AIOS_RESPONSE_PATH": str(response),
            "AIOS_LAMBDA_PATH": str(lambda_path),
            "AIOS_CONSTRAINTS_PATH": str(constraints),
            "AIOS_SEARCH_BUDGET": str(args.budget),
            "AIOS_SEARCH_OUTPUT": str(out / "cmaes.json"),
            "AIOS_SUBMISSION_WORK_ROOT": str(out / "opm"),
            "AIOS_RESULT_PATH": str(out / "result.json"),
            "AIOS_SUBMISSION_SCHEDULE_PATH": str(out / "wells_schedule.inc"),
            "AIOS_OUT_DIR": str(out),
            "AIOS_SEED": str(args.seed),
            "PYTHONHASHSEED": "0",
            "AIOS_OOD_THRESHOLD": str(args.ood_threshold),
        }
    )
    if args.surrogate_bundle is not None:
        env["AIOS_SURROGATE_BUNDLE"] = str(
            _require_dir(args.surrogate_bundle, "production surrogate bundle")
        )
        env.pop("AIOS_SURROGATE_MANIFEST", None)
    elif args.surrogate_manifest is not None:
        env["AIOS_SURROGATE_MANIFEST"] = str(
            _require_file(args.surrogate_manifest, "production surrogate manifest")
        )
        env.pop("AIOS_SURROGATE_BUNDLE", None)

    artifacts = resolve_runtime_artifacts(env)
    if artifacts.npv_head is None:
        raise SystemExit(
            "production E2E требует совместимый NPV head рядом с trajectory "
            "ensemble; physical-only кандидат разрешён для исследований, но не "
            "для финального shortlist"
        )
    config = {
        "format": "aios.e2e-invocation.v1",
        "model_dir": str(model),
        "normatives": str(normatives),
        "response": str(response),
        "lambda": str(lambda_path),
        "constraints": str(constraints),
        "surrogate_source": artifacts.source,
        "trajectory_checkpoint": str(artifacts.checkpoint.resolve()),
        "feature_context": str(artifacts.feature_context.resolve()),
        "npv_head": str(artifacts.npv_head.resolve()) if artifacts.npv_head else None,
        "budget": args.budget,
        "seed": args.seed,
        "ood_threshold": args.ood_threshold,
    }
    (out / "invocation.json").write_text(
        json.dumps(config, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    return env, out


def _run_stage(module: str, env: dict[str, str], *arguments: str) -> int:
    command = [sys.executable, "-m", module, *arguments]
    completed = subprocess.run(command, env=env, check=False)
    return completed.returncode


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    env, out = _runtime_environment(args)
    search_artifact = out / "cmaes.json"

    print(f"E2E output: {out}", flush=True)
    if not args.verify_only:
        print("\n[1/2] surrogate search", flush=True)
        code = _run_stage("optimizer.search_run", env, str(args.budget))
        if code != 0:
            print(f"surrogate search failed with code {code}", file=sys.stderr)
            return code
    elif not search_artifact.is_file():
        raise SystemExit(f"--verify-only требует {search_artifact}")

    if args.search_only:
        print(f"\nsearch artifact: {search_artifact}", flush=True)
        return 0

    if shutil.which("docker") is None:
        raise SystemExit("полный E2E требует Docker для настоящего OPM Flow")
    print("\n[2/2] OPM verification and methodology NPV", flush=True)
    code = _run_stage("bridge.submission_run", env)
    if code != 0:
        print(f"OPM verification failed with code {code}", file=sys.stderr)
        return code

    result_path = out / "result.json"
    if not result_path.is_file():
        raise SystemExit(f"submission stage did not produce {result_path}")
    result = json.loads(result_path.read_text(encoding="utf-8"))
    if result.get("sound") is not True:
        print("result is not sound and cannot be submitted", file=sys.stderr)
        return 6
    print(f"\nE2E complete: {result_path}", flush=True)
    print(f"submission schedule: {out / 'wells_schedule.inc'}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
