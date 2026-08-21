import { describe, expect, it } from 'vitest';
import type { ScenarioConstraintsSummary, ScenarioEntry } from '../../api/types';
import { buildVerdict } from './verdict';

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

const clean = { synthetic: false, provenance: 'run' };
const demo = { synthetic: true, provenance: 'synthetic-demo' };

describe('trust verdict synthesis priority', () => {
  it('lets synthetic-demo provenance beat a green convergence', () => {
    const verdict = buildVerdict(
      scenario({
        converged: true,
        self_consistent: true,
        final_npv: { npv_rub: 1, run_id: 'r' },
        run_validation_clean: true
      }),
      demo
    );
    expect(verdict.kind).toBe('syntheticDemo');
    expect(verdict.level).toBe('warn');
  });

  it('confirms the run identifier when final_npv is present with clean validation', () => {
    const verdict = buildVerdict(
      scenario({ final_npv: { npv_rub: 10786000000, run_id: 'run-7f3a' }, run_validation_clean: true }),
      clean
    );
    expect(verdict.kind).toBe('confirmed');
    expect(verdict.level).toBe('ok');
    expect(verdict.labelParams).toEqual({ run: 'run-7f3a' });
  });

  it('marks the chip amber when final_npv is present but validation is absent', () => {
    const verdict = buildVerdict(
      scenario({ final_npv: { npv_rub: 10786000000, run_id: 'run-7f3a' } }),
      clean
    );
    expect(verdict.kind).toBe('unconfirmedNumber');
    expect(verdict.level).toBe('warn');
  });

  it('marks the chip amber when final_npv is present but validation carries violations', () => {
    const verdict = buildVerdict(
      scenario({
        final_npv: { npv_rub: 10786000000, run_id: 'run-7f3a' },
        run_validation_clean: false
      }),
      clean
    );
    expect(verdict.kind).toBe('unconfirmedNumber');
    expect(verdict.level).toBe('warn');
  });

  it('flags out-of-domain before convergence when no final_npv is present', () => {
    const verdict = buildVerdict(
      scenario({ ood_score: 0.9, ood_threshold: 0.5, converged: false }),
      clean
    );
    expect(verdict.kind).toBe('outOfDomain');
  });

  it('flags a fixed point that did not converge once domain is in range', () => {
    const verdict = buildVerdict(
      scenario({ ood_score: 0.2, ood_threshold: 0.5, converged: false }),
      clean
    );
    expect(verdict.kind).toBe('notConverged');
  });

  it('flags self-inconsistency the same way as non-convergence', () => {
    const verdict = buildVerdict(
      scenario({ ood_score: 0.2, ood_threshold: 0.5, self_consistent: false }),
      clean
    );
    expect(verdict.kind).toBe('notConverged');
  });

  it('reports the missing field when domain is not measured', () => {
    const verdict = buildVerdict(scenario({ ood_score: null, ood_threshold: null }), clean);
    expect(verdict.kind).toBe('missingField');
    expect(verdict.labelParams?.field).toBe('trust.label.domain');
  });

  it('falls back to a neutral in-domain surrogate verdict when everything checks out', () => {
    const verdict = buildVerdict(scenario({ ood_score: 0.1, ood_threshold: 0.5 }), clean);
    expect(verdict.kind).toBe('inDomain');
    expect(verdict.level).toBe('neutral');
  });
});
