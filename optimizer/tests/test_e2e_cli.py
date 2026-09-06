from __future__ import annotations

import json
from pathlib import Path

from aios_cli import e2e


def _inputs(tmp_path: Path) -> dict[str, Path]:
    model = tmp_path / "Model_Z"
    model.mkdir()
    normatives = tmp_path / "Нормативы_ЧДД.xlsx"
    response = tmp_path / "response.json"
    lambda_path = tmp_path / "lambda.json"
    for path in (normatives, response, lambda_path):
        path.write_text("artifact", encoding="utf-8")
    constraints = tmp_path / "constraints.json"
    constraints.write_text(
        json.dumps(
            {
                "injection_limits": {},
                "liquid_limits": {},
                "production_floors": {},
                "watercut_limits": {},
                "well_outages": [],
                "infrastructure": {
                    "water_reinjection_fraction": 1.0,
                    "external_water_m3_per_day": 0.0,
                },
            }
        ),
        encoding="utf-8",
    )
    guard = tmp_path / "scenario.pt"
    guard.write_bytes(b"guard")
    bundle = tmp_path / "surrogate"
    (bundle / "physical").mkdir(parents=True)
    (bundle / "physical" / "trajectory_ensemble.json").write_text("{}")
    (bundle / "physical" / "npv_head.pt").write_text("head")
    (bundle / "feature_context.json").write_text("{}")
    return {
        "model": model,
        "normatives": normatives,
        "response": response,
        "lambda": lambda_path,
        "constraints": constraints,
        "bundle": bundle,
        "guard": guard,
        "out": tmp_path / "out",
    }


def _argv(paths: dict[str, Path], *extra: str) -> list[str]:
    return [
        "--model-dir",
        str(paths["model"]),
        "--normatives",
        str(paths["normatives"]),
        "--response",
        str(paths["response"]),
        "--lambda-path",
        str(paths["lambda"]),
        "--constraints",
        str(paths["constraints"]),
        "--surrogate-bundle",
        str(paths["bundle"]),
        "--scenario-ood",
        str(paths["guard"]),
        "--out",
        str(paths["out"]),
        *extra,
    ]


def test_search_only_pins_all_runtime_artifacts(monkeypatch, tmp_path) -> None:
    paths = _inputs(tmp_path)
    calls: list[tuple[str, dict[str, str], tuple[str, ...]]] = []

    def fake_run(module: str, env: dict[str, str], *arguments: str) -> int:
        calls.append((module, env, arguments))
        return 0

    monkeypatch.setattr(e2e, "_run_stage", fake_run)
    assert e2e.main(_argv(paths, "--search-only", "--budget", "10")) == 0

    assert len(calls) == 1
    module, env, arguments = calls[0]
    assert module == "optimizer.search_run"
    assert arguments == ("10",)
    assert env["AIOS_SURROGATE_BUNDLE"] == str(paths["bundle"].resolve())
    assert env["AIOS_SEARCH_OUTPUT"] == str(paths["out"].resolve() / "cmaes.json")
    invocation = json.loads(
        (paths["out"] / "invocation.json").read_text(encoding="utf-8")
    )
    assert invocation["npv_head"].endswith("physical/npv_head.pt")
    assert invocation["scenario_ood"] == str(paths["guard"].resolve())
    assert env["AIOS_SCENARIO_OOD_PATH"] == str(paths["guard"].resolve())


def test_full_e2e_requires_sound_submission(monkeypatch, tmp_path) -> None:
    paths = _inputs(tmp_path)
    modules: list[str] = []

    def fake_run(module: str, env: dict[str, str], *arguments: str) -> int:
        modules.append(module)
        out = paths["out"]
        if module == "optimizer.search_run":
            (out / "cmaes.json").write_text("{}", encoding="utf-8")
        else:
            (out / "result.json").write_text(
                json.dumps({"sound": True}), encoding="utf-8"
            )
            (out / "wells_schedule.inc").write_text("schedule", encoding="utf-8")
        return 0

    monkeypatch.setattr(e2e, "_run_stage", fake_run)
    monkeypatch.setattr(e2e.shutil, "which", lambda _: "/usr/bin/docker")
    assert e2e.main(_argv(paths, "--budget", "10")) == 0
    assert modules == ["optimizer.search_run", "bridge.submission_run"]


def test_production_e2e_rejects_bundle_without_npv_head(tmp_path) -> None:
    paths = _inputs(tmp_path)
    (paths["bundle"] / "physical" / "npv_head.pt").unlink()
    try:
        e2e.main(_argv(paths, "--search-only"))
    except SystemExit as error:
        assert "NPV head" in str(error)
    else:
        raise AssertionError("physical-only bundle entered production E2E")


def test_production_e2e_rejects_missing_density_guard(tmp_path, monkeypatch):
    import pytest
    monkeypatch.delenv('AIOS_SCENARIO_OOD_PATH', raising=False)
    paths = _inputs(tmp_path)
    args = _argv(paths, '--search-only')
    at = args.index('--scenario-ood')
    del args[at:at + 2]
    with pytest.raises(SystemExit, match='сценарный OOD'):
        e2e.main(args)
