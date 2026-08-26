import { describe, expect, it } from 'vitest';
import type { ScenarioConstraintsSummary, ScenarioEntry } from '../../api/types';
import { isScenariosFile } from '../../data/validators';
import { buildIndicators } from './indicators';

const summary = (): ScenarioConstraintsSummary => ({
  injection_limits: 0,
  liquid_limits: 0,
  production_floors: 0,
  watercut_limits: 0,
  well_outages: 0,
  infrastructure: 0,
  years: [],
  outage_wells: [],
  empty: true
});

const scenario = (overrides: Partial<ScenarioEntry> = {}): ScenarioEntry => ({
  id: 'base',
  config_hash: 'a'.repeat(64),
  converged: true,
  self_consistent: true,
  is_submitted: true,
  npv_methodology: null,
  constraints: summary(),
  ...overrides
});

describe('trust indicators built from a scenario entry', () => {
  const source = { provenance: 'run' };

  it('never reports a measured status for an absent field', () => {
    const byId = Object.fromEntries(
      buildIndicators(scenario(), source).map((one) => [one.id, one])
    );

    expect(byId.domain.status).toBe('unmeasured');
    expect(byId.regret.status).toBe('unmeasured');
    expect(byId.number.status).toBe('unmeasured');
    expect(byId.domain.valueKey).toBe('trust.unmeasured');
    expect(byId.regret.valueKey).toBe('trust.unmeasured');
  });

  it('reads the threshold from the artifact rather than assuming one', () => {
    const lenient = buildIndicators(
      scenario({ ood_score: 0.6, ood_threshold: 0.9 }),
      source
    );
    const strict = buildIndicators(
      scenario({ ood_score: 0.6, ood_threshold: 0.4 }),
      source
    );

    expect(lenient[2].valueKey).toBe('trust.domain.inside');
    expect(strict[2].valueKey).toBe('trust.domain.outside');
  });

  it('treats a half-measured domain as unmeasured rather than guessing', () => {
    const noThreshold = buildIndicators(scenario({ ood_score: 0.6 }), source);
    const noScore = buildIndicators(scenario({ ood_threshold: 0.4 }), source);

    expect(noThreshold[2].status).toBe('unmeasured');
    expect(noScore[2].status).toBe('unmeasured');
  });
});

describe('scenarios validator with trust fields', () => {
  const base = { id: 'base', constraints: {} };

  it('accepts a bundle that carries none of the trust fields', () => {
    expect(isScenariosFile({ scenarios: [base] })).toBe(true);
  });

  it('accepts explicit nulls in every trust field', () => {
    expect(
      isScenariosFile({
        scenarios: [
          {
            ...base,
            ood_score: null,
            ood_threshold: null,
            worst_regret: null,
            final_npv: null
          }
        ]
      })
    ).toBe(true);
  });

  it('accepts fully measured trust fields', () => {
    expect(
      isScenariosFile({
        scenarios: [
          {
            ...base,
            ood_score: 0.18,
            ood_threshold: 0.5,
            worst_regret: { scenario_id: 'S-07', value_rub: 201000000, part: 'holdout' },
            final_npv: { npv_rub: 1, run_id: 'r' }
          }
        ]
      })
    ).toBe(true);
  });

  it('rejects a malformed regret or final npv rather than rendering half of it', () => {
    expect(
      isScenariosFile({ scenarios: [{ ...base, worst_regret: { scenario_id: 'S-07' } }] })
    ).toBe(false);
    expect(
      isScenariosFile({
        scenarios: [
          { ...base, worst_regret: { scenario_id: 'S', value_rub: 1, part: 'other' } }
        ]
      })
    ).toBe(false);
    expect(isScenariosFile({ scenarios: [{ ...base, final_npv: { npv_rub: 1 } }] })).toBe(
      false
    );
  });
});
