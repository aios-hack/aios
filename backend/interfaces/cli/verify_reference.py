import argparse
import hashlib
import json
import math
from pathlib import Path

from backend.core.contracts import ChargeInitialEsp, Policies, QuantizationPolicy
from backend.domain.economics import analyze_base_case, load_response_artifact, load_normatives
from backend.contexts.economics.application.base_case import (
    responses_by_well_from_artifact,
    states_by_well_from_artifact,
)
from backend.contexts.economics.application.reference_parity import (
    build_reference_records,
    compare_with_reference,
    run_reference,
)
from backend.domain.schedule import parse_schedule
from backend.shared.resources import model_z_dir, chdd_python_dir, normatives_xlsx
from backend.interfaces.cli.run import load_run_request
from backend.interfaces.cli.runner import run as run_cli
from backend.shared.json_io import read_json


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-dir", type=Path, required=True)
    args = parser.parse_args(argv)
    run = args.run_dir
    load_run_request(run.parent, run.name)
    manifest = read_json(run / 'manifest.json')
    normatives_path = normatives_xlsx()
    if manifest.get("normatives_sha256") != hashlib.sha256(normatives_path.read_bytes()).hexdigest():
        parser.error("Current normatives differ from the measured run")
    artifact = load_response_artifact(run / "response.json")
    parsed = parse_schedule((model_z_dir() / "Model_Z_sch.inc").read_bytes())
    normatives = load_normatives(normatives_path)
    policies = Policies(charge_initial_esp=ChargeInitialEsp.NOT_CHARGED,
                        quantization_policy=QuantizationPolicy.NONE)
    analysis = analyze_base_case(artifact, parsed.dates, parsed.t0_deck_date_index, normatives, policies)
    records = build_reference_records(states_by_well_from_artifact(artifact),
                                      responses_by_well_from_artifact(artifact), analysis.interval_start_dates)
    calculator = chdd_python_dir() / "chdd_model.py"
    reference = run_reference(calculator.parent, records, normatives, policies,
                              start_date=analysis.interval_start_dates[0])
    report = compare_with_reference(analysis.table, reference, analysis.interval_start_dates)
    measured = read_json(run / 'economics/result.json')["measured_npv"]
    payload = dict(npv_ours=report.npv_ours, npv_reference=report.npv_reference,
                   absolute_difference=report.npv_absolute, discrepancies=len(report.discrepancies),
                   matched=report.matched, saved_measured_npv=measured,
                   saved_measurement_matches=math.isfinite(measured) and abs(measured - report.npv_ours) < 0.01,
                   calculator_sha256=hashlib.sha256(calculator.read_bytes()).hexdigest(),
                   control_start=analysis.interval_start_dates[0].isoformat())
    (run / "economics/reference-parity.json").write_text(json.dumps(payload, indent=2) + "\n")
    print(json.dumps(payload, indent=2))
    return 0 if payload["matched"] and payload["saved_measurement_matches"] else 1


if __name__ == "__main__":
    raise SystemExit(run_cli(main))
