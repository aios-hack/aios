"""Freeze an unseen-case prediction before OPM, then report temporal errors.

Usage: python scripts/audit_unseen_run.py --run-dir out/web-runs/<id>
       python scripts/audit_unseen_run.py --run-dir out/web-runs/<id> --report
The report never fits or changes a model. Paths describe the current locked
production training population, including the economic head's augmentations.
"""
from __future__ import annotations
import argparse
from collections import defaultdict
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

SOURCES = (
    'data/model-night-20260826-v2/npv_labels.json',
    'data/npv-v4/blind1_labels_disclosed.json',
    'data/npv-v5/blind2_labels_disclosed.json',
    'data/npv-v6/blind3_labels_disclosed.json',
)

def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def lock(root):
    import torch
    from backend.contexts.optimization.infrastructure.artifacts import resolve_runtime_artifacts
    from backend.contexts.optimization.application.environment import (
        load_environment,
        make_evaluator,
    )
    from backend.contexts.constraints.infrastructure.constraints_io import constraints_from_json
    from backend.contexts.schedule.infrastructure.json_io import load_schedule_json
    from backend.core.contracts import hash_schedule
    from backend.domain.economics import save_response_artifact
    from backend.shared.resources import model_z_dir, normatives_xlsx
    manifest = json.loads((root / 'manifest.json').read_text())
    if manifest['verified_npv'] is not None or list(root.glob('opm/runs/*/command.txt')):
        raise RuntimeError('Prediction must be frozen before the first OPM run.')
    destination = root / 'prediction/response.json'
    if destination.exists():
        raise RuntimeError('A frozen prediction already exists; refusing to replace it.')
    fitted, known, audit = set(), set(), []
    for index, source in enumerate(SOURCES):
        rows = json.loads(Path(source).read_text())['rows'].values()
        all_hashes = {row['canonical_schedule_hash'] for row in rows}
        fit_hashes = {row['canonical_schedule_hash'] for row in rows
                      if index > 0 or row['bucket'] in ('train', 'validation')}
        fitted.update(fit_hashes); known.update(all_hashes)
        audit.append({'path': source, 'sha256': sha(source), 'known_unique': len(all_hashes), 'fit_unique': len(fit_hashes)})
    schedule_hash = manifest['schedule_hash']
    if schedule_hash in known:
        raise RuntimeError('This exact schedule already occurs in the audited populations.')
    torch.set_num_threads(2)
    artifacts = resolve_runtime_artifacts()
    constraints = constraints_from_json(json.loads((root / 'constraints.json').read_text()))
    env = load_environment(model_dir=model_z_dir(), normatives_path=normatives_xlsx(),
        response_path=Path('data/base_case/response.json'), lambda_path=Path('data/lambda-window-2007/lambda.json'),
        checkpoint_path=artifacts.checkpoint, feature_context_path=artifacts.feature_context,
        npv_head_path=artifacts.npv_head, scenario_ood_path=artifacts.scenario_ood, constraints=constraints)
    schedule = load_schedule_json(root / 'schedule/schedule.json')
    if hash_schedule(schedule) != schedule_hash:
        raise RuntimeError('Saved schedule does not match its manifest.')
    prediction = make_evaluator(env)(schedule)
    if abs(prediction.npv - manifest['predicted_npv']) > .01:
        raise RuntimeError('Prediction no longer matches the selected run.')
    save_response_artifact(prediction.state.response, destination)
    protocol = {
        'locked_at_utc': datetime.now(timezone.utc).isoformat(),
        'case': 'well-17-apr-sep-2017-plus-liquid-1650',
        'constraints': json.loads((root / 'constraints.json').read_text()),
        'candidate_schedule_hash': schedule_hash, 'exact_fit_overlap': False, 'exact_known_overlap': False,
        'fitted_schedule_hashes_count': len(fitted), 'all_known_schedule_hashes_count': len(known),
        'audit_sources': audit, 'production_manifest_sha256': sha('data/surrogate-production.json'),
        'prediction_locked': prediction.npv, 'prediction_response_sha256': sha(destination),
        'control_dates': [date.isoformat() for date in env.control_dates],
        'retraining_performed': False, 'opm_result_seen_at_lock': False,
    }
    (root / 'unseen-protocol.json').write_text(json.dumps(protocol, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps({k: v for k, v in protocol.items() if k not in ('control_dates', 'audit_sources')}, ensure_ascii=False, indent=2))


def report(root, reference=None):
    from backend.domain.economics import load_response_artifact
    protocol = json.loads((root / 'unseen-protocol.json').read_text())
    if sha(root / 'prediction/response.json') != protocol['prediction_response_sha256']:
        raise RuntimeError('Frozen prediction was changed.')
    if sha('data/surrogate-production.json') != protocol['production_manifest_sha256']:
        raise RuntimeError('Production pointer changed during the experiment.')
    manifest = json.loads((root / 'manifest.json').read_text())
    if manifest['schedule_hash'] != protocol['candidate_schedule_hash']:
        raise RuntimeError('A different plan was verified.')
    observation = root / 'observation' / manifest['schedule_hash']
    actual = load_response_artifact(observation / 'response.json')
    predicted = load_response_artifact(root / 'prediction/response.json')
    columns = ('oil_mass_delta', 'liquid_volume_delta', 'injection_volume_delta')
    def aggregate(response):
        groups = defaultdict(lambda: {col: 0.0 for col in columns})
        for row in response.interval_response:
            year = protocol['control_dates'][row.control_step][:4]
            for col in columns: groups[year][col] += getattr(row, col)
        return groups
    p, a = aggregate(predicted), aggregate(actual)
    yearly = {}
    for year in sorted(a):
        yearly[year] = {col: {'predicted': p[year][col], 'opm': a[year][col],
            'absolute_error_pct': 100 * abs(p[year][col] - a[year][col]) / abs(a[year][col]) if a[year][col] else None}
            for col in columns}
    dates = [datetime.fromisoformat(value) for value in protocol['control_dates']]
    actual_liquid = defaultdict(float)
    for row in actual.interval_response:
        if dates[row.control_step].year == 2017:
            actual_liquid[row.control_step] += row.liquid_volume_delta
    outage_rows = [row for row in actual.interval_response if row.well == '17' and 123 <= row.control_step <= 128]
    constraint_measurements = {
        'outage_well_17_liquid_m3': sum(row.liquid_volume_delta for row in outage_rows),
        'outage_well_17_oil_t': sum(row.oil_mass_delta for row in outage_rows),
        'maximum_2017_monthly_mean_liquid_m3_per_day': max(volume / (dates[step+1] - dates[step]).days for step, volume in actual_liquid.items()),
        'liquid_cap_m3_per_day': 1650,
    }
    npv = json.loads((observation / 'observation.json').read_text())['opm_npv']
    output = {'run_id': root.name, 'focus_year': '2017', 'fitted_schedule_hashes_count': protocol['fitted_schedule_hashes_count'], 'exact_fit_overlap': False, 'exact_known_overlap': False,
        'predicted_npv': protocol['prediction_locked'], 'opm_npv': npv,
        'npv_absolute_error_pct': 100 * abs(npv - protocol['prediction_locked']) / abs(npv),
        'validation': json.loads((root / 'validation/result.json').read_text()), 'constraint_measurements': constraint_measurements, 'yearly': yearly}
    if reference is not None:
        ref_manifest = json.loads((reference / 'manifest.json').read_text())
        if ref_manifest['verified_npv'] is None:
            raise RuntimeError('Reference run is not verified.')
        ref_response = load_response_artifact(reference / 'observation' / ref_manifest['schedule_hash'] / 'response.json')
        ref_yearly = aggregate(ref_response)
        predicted_effect = protocol['prediction_locked'] - ref_manifest['predicted_npv']
        actual_effect = npv - ref_manifest['verified_npv']
        output['paired_comparison'] = {
            'reference_run_id': reference.name,
            'reference_2017_liquid_peak_m3_per_day': max(sum(row.liquid_volume_delta for row in ref_response.interval_response if row.control_step == step) / (dates[step+1] - dates[step]).days for step in actual_liquid),
            'reference_outage_window_well17_oil_t': sum(row.oil_mass_delta for row in ref_response.interval_response if row.well == '17' and 123 <= row.control_step <= 128),
            'reference_outage_window_well17_liquid_m3': sum(row.liquid_volume_delta for row in ref_response.interval_response if row.well == '17' and 123 <= row.control_step <= 128),
            'predicted_npv_change_rub': predicted_effect,
            'opm_npv_change_rub': actual_effect,
            'effect_error_rub': predicted_effect - actual_effect,
            'effect_absolute_error_pct': 100 * abs(predicted_effect - actual_effect) / abs(actual_effect) if actual_effect else None,
            '2017_opm_change': {col: a['2017'][col] - ref_yearly['2017'][col] for col in columns},
        }
    (root / 'unseen-result.json').write_text(json.dumps(output, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps({**output, 'yearly': {'2017': yearly['2017']}}, ensure_ascii=False, indent=2))

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run-dir', required=True, type=Path)
    parser.add_argument('--report', action='store_true')
    parser.add_argument('--reference-run-dir', type=Path)
    args = parser.parse_args()
    if args.report: report(args.run_dir, args.reference_run_dir)
    else: lock(args.run_dir)
