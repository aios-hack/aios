import { describe, expect, it } from 'vitest';
import type { ScenarioEntry } from '../../api/types';
import { dictionaries } from '../../i18n/dictionaries';
import { isSyntheticArtifact, npvProvenanceOf } from './provenance';

const emptyConstraints: ScenarioEntry['constraints'] = {
  injection_limits: 0,
  liquid_limits: 0,
  production_floors: 0,
  watercut_limits: 0,
  well_outages: 0,
  infrastructure: 0,
  years: [],
  outage_wells: [],
  empty: true
};

const scenario = (patch: Partial<ScenarioEntry>): ScenarioEntry => ({
  id: 'case',
  config_hash: 'hash',
  converged: true,
  self_consistent: true,
  is_submitted: false,
  npv_methodology: null,
  constraints: emptyConstraints,
  ...patch
});

const confirmed = scenario({
  id: 'base',
  npv_methodology: 11873122324.910866,
  final_npv: { npv_rub: 11873122324.910866, run_id: '20260816T200926-8b4da543d1ed' },
  run_validation_clean: true
});

const forecastOnly = scenario({
  id: 'candidate',
  predicted_npv_rub: 10558445546.343525,
  ood_score: 2.0197874298096283,
  ood_threshold: 0,
  run_validation_clean: null
});

const notMeasured = scenario({
  id: 'whatif-injection-cut',
  final_npv: null,
  predicted_npv_rub: null,
  npv_methodology: null,
  run_validation_clean: null
});

describe('npvProvenanceOf', () => {
  it('marks a clean run-confirmed number as confirmed by a simulator run', () => {
    const result = npvProvenanceOf(confirmed, { kind: 'scenarios', provenance: 'model-z-base-run' });

    expect(result.kind).toBe('run');
    expect(result.labelKey).toBe('npv.provenance.run');
    expect(result.params?.run).toBe('20260816T200926-8b4da543d1ed');
  });

  it('marks a number that only the model produced as a forecast, not a fact', () => {
    const result = npvProvenanceOf(forecastOnly, undefined);

    expect(result.kind).toBe('forecast');
    expect(result.labelKey).toBe('npv.provenance.forecast');
    expect(result.noteKey).toBe('npv.provenance.forecastOutside');
  });

  it('says plainly that nothing was measured when there is neither run nor forecast', () => {
    const result = npvProvenanceOf(notMeasured, undefined);

    expect(result.kind).toBe('unmeasured');
    expect(result.labelKey).toBe('npv.provenance.unmeasured');
  });

  it('refuses to call a run confirmed when its validation is not clean', () => {
    const dirty = scenario({
      final_npv: { npv_rub: 1, run_id: 'run-1' },
      run_validation_clean: false
    });

    const result = npvProvenanceOf(dirty, undefined);

    expect(result.kind).toBe('unmeasured');
    expect(result.labelKey).toBe('npv.provenance.runDirty');
  });

  it('falls back to the methodology label when only the methodology number exists', () => {
    const result = npvProvenanceOf(scenario({ npv_methodology: 42 }), undefined);

    expect(result.kind).toBe('methodology');
  });

  it('carries the pre-run forecast alongside a confirmed number', () => {
    const both = scenario({
      final_npv: { npv_rub: 7781051025, run_id: 'run-2' },
      predicted_npv_rub: 10558445546,
      run_validation_clean: true
    });

    const result = npvProvenanceOf(both, undefined);

    expect(result.kind).toBe('run');
    expect(result.noteKey).toBe('npv.provenance.runVersusForecast');
    expect(result.noteParams?.predicted).toBe(10558445546);
  });

  it('reports a missing scenario as not measured rather than guessing', () => {
    expect(npvProvenanceOf(undefined, undefined).kind).toBe('unmeasured');
  });

  it('flags synthetic artifacts by the flag and by the provenance string', () => {
    expect(isSyntheticArtifact({ kind: 'scenarios', provenance: 'synthetic-demo' })).toBe(true);
    expect(
      isSyntheticArtifact({ kind: 'scenarios', provenance: 'model-z-base-run', synthetic: true })
    ).toBe(true);
    expect(isSyntheticArtifact({ kind: 'scenarios', provenance: 'model-z-base-run' })).toBe(false);
    expect(isSyntheticArtifact(undefined)).toBe(false);
  });

  it('keeps every provenance key present in both dictionaries', () => {
    const keys = [
      'npv.provenance.run',
      'npv.provenance.runDirty',
      'npv.provenance.runVersusForecast',
      'npv.provenance.forecast',
      'npv.provenance.forecastInside',
      'npv.provenance.forecastOutside',
      'npv.provenance.methodology',
      'npv.provenance.unmeasured',
      'npv.provenance.synthetic',
      'npv.provenance.title'
    ];

    for (const key of keys) {
      expect(dictionaries.ru[key]).toBeTypeOf('string');
      expect(dictionaries.en[key]).toBeTypeOf('string');
    }
  });
});
