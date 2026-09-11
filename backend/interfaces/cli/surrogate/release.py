from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
import tempfile
from pathlib import Path

from backend.contexts.optimization.infrastructure.artifacts import (
    BundleVerdict,
    RuntimeArtifactError,
    resolve_runtime_artifacts,
    validate_runtime_economic_head,
    verify_bundle,
)
from backend.contexts.optimization.application.environment import _validate_npv_head_compatibility
from backend.contexts.surrogate.application.ensemble import TrajectoryEnsemble
from backend.contexts.surrogate.application.model import TrajectorySurrogate
from backend.contexts.surrogate.domain.npv_block_head import load_direct_npv_head
from backend.contexts.robustness.domain.scenario_ood import ScenarioDensityDomain
from backend.interfaces.cli.runner import run as run_cli


def package(manifest: Path, destination: Path) -> Path:
    if destination.exists():
        raise FileExistsError(f"release already exists: {destination}")
    manifest = manifest.resolve()
    root = manifest.parent
    artifacts = resolve_runtime_artifacts({"AIOS_SURROGATE_MANIFEST": str(manifest)})
    model = (TrajectoryEnsemble.load(artifacts.checkpoint) if artifacts.checkpoint.suffix == ".json"
             else TrajectorySurrogate.load(artifacts.checkpoint))
    head = load_direct_npv_head(artifacts.npv_head)
    validate_runtime_economic_head(artifacts, head)
    _validate_npv_head_compatibility(head, model, artifacts.feature_context)
    domain = ScenarioDensityDomain.load(artifacts.scenario_ood)
    if domain.dataset_hash != model.dataset_hash:
        raise ValueError("scenario OOD belongs to a different dataset")
    paths = [manifest, artifacts.checkpoint, artifacts.feature_context, artifacts.npv_head, artifacts.scenario_ood]
    if isinstance(model, TrajectoryEnsemble):
        paths.extend(model.member_paths)
    relative = {path.resolve().relative_to(root): path.resolve() for path in paths}
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".surrogate-release-", dir=destination.parent) as temporary:
        staging = Path(temporary) / "bundle"
        staging.mkdir()
        for target, source in relative.items():
            output = staging / target
            output.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, output)
        metadata = {
            "format": "aios.surrogate-release.v1", "weights_changed": False,
            "trajectory_version": model.version, "economic_version": head.version,
            "scenario_ood_version": domain.version,
            "manifest": str(manifest.relative_to(root)),
            "files_sha256": {str(path): hashlib.sha256((staging / path).read_bytes()).hexdigest()
                             for path in sorted(relative)},
        }
        (staging / "release.json").write_text(json.dumps(metadata, indent=2, sort_keys=True) + "\n")
        resolve_runtime_artifacts({"AIOS_SURROGATE_MANIFEST": str(staging / manifest.name)})
        staging.rename(destination)
    return destination / manifest.name


def render_verdict(verdict: BundleVerdict, show_extra: bool = False) -> str:
    lines = [
        f"bundle: {verdict.root}",
        f"inventory: {verdict.reference} ({verdict.reference_format})",
        f"files checked: {len(verdict.files)}",
    ]
    for item in verdict.mismatched:
        if item.status == "missing":
            lines.append(f"MISSING {item.path}: expected {item.expected_sha256}")
        else:
            lines.append(
                f"MISMATCH {item.path}: expected {item.expected_sha256}, "
                f"got {item.actual_sha256}"
            )
    if verdict.extra_files:
        lines.append(
            f"files outside the inventory: {len(verdict.extra_files)} "
            "(they do not affect the integrity verdict)"
        )
        if show_extra:
            lines.extend(f"  outside the inventory: {name}" for name in verdict.extra_files)
    lines.append(
        "verdict: the bundle is intact"
        if verdict.ok
        else f"verdict: the bundle is corrupted, {len(verdict.mismatched)} mismatches"
    )
    return "\n".join(lines) + "\n"


def _write_stdout(text: str) -> None:
    encoding = sys.stdout.encoding or "utf-8"
    sys.stdout.write(text.encode(encoding, errors="backslashreplace").decode(encoding))
    sys.stdout.flush()


def verify(
    root: Path,
    reference: Path | None,
    output: Path | None,
    as_json: bool,
    show_extra: bool = False,
) -> int:
    verdict = verify_bundle(root, reference)
    rendered = (
        json.dumps(verdict.as_dict(), ensure_ascii=False, indent=2, sort_keys=True) + "\n"
        if as_json
        else render_verdict(verdict, show_extra)
    )
    if output is not None:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(rendered, encoding="utf-8")
    _write_stdout(rendered)
    return verdict.exit_code


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Package verified production weights and check an already installed "
            "bundle against the checksum inventory"
        )
    )
    commands = parser.add_subparsers(dest="command", required=True)
    packaging = commands.add_parser("package")
    packaging.add_argument("--manifest", type=Path, required=True)
    packaging.add_argument("--output", type=Path, required=True)
    checking = commands.add_parser("verify")
    checking.add_argument("--root", type=Path, required=True)
    checking.add_argument("--reference", type=Path)
    checking.add_argument("--output", type=Path)
    checking.add_argument("--json", action="store_true")
    checking.add_argument("--show-extra", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "package":
        print(package(args.manifest, args.output))
        return 0
    try:
        return verify(
            args.root, args.reference, args.output, args.json, args.show_extra
        )
    except RuntimeArtifactError as error:
        print(f"the check was not performed: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(run_cli(main))
