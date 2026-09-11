import { describe, expect, it } from 'vitest';
import type { ScenarioConstraintsSummary, ScenarioEntry, ScenarioPhysics } from '@/entities/scenarios/types';
import { isScenariosFile } from '@/entities/scenarios/validate';
import { buildIndicators, type TrustIndicator } from '@/features/trust-board/ui/indicators';
import ru from '@/shared/i18n/locales/ru/trust.json';
import en from '@/shared/i18n/locales/en/trust.json';

const ALL_SEVEN: string[] = [
  'NON_NEGATIVE',
  'WATERCUT_RANGE',
  'CUMULATIVE_MONOTONIC',
  'SHUT_WELL_FLOW',
  'BHP_LIMIT',
  'INJECTION_RESPONSE',
  'MATERIAL_BALANCE'
];

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

const physics = (overrides: Partial<ScenarioPhysics> = {}): ScenarioPhysics => ({
  total: 7,
  evaluated_count: 7,
  evaluated: ALL_SEVEN,
  skipped: [],
  blocking_count: 0,
  warning_count: 0,
  complete: true,
  admissible: true,
  warning_invariants: ['BHP_LIMIT'],
  ...overrides
});

const partial = (): ScenarioPhysics =>
  physics({
    evaluated_count: 5,
    evaluated: ALL_SEVEN.slice(0, 5),
    skipped: [
      {
        invariant: 'INJECTION_RESPONSE',
        reason: 'нет опорного прогноза',
        severity: 'BLOCKING'
      },
      {
        invariant: 'MATERIAL_BALANCE',
        reason: 'нет опорного прогноза',
        severity: 'BLOCKING'
      }
    ],
    complete: false,
    admissible: false
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

const indicatorOf = (entry: ScenarioEntry): TrustIndicator => {
  const found = buildIndicators(entry, { provenance: 'run' }).find(
    (one) => one.id === 'physics'
  );
  if (found === undefined) {
    throw new Error('индикатор физпроверок не собран');
  }
  return found;
};

describe('trust physics indicator', () => {
  it('is part of the trust board indicators', () => {
    const ids = buildIndicators(scenario(), { provenance: 'run' }).map((one) => one.id);
    expect(ids).toContain('physics');
  });

  it('reports "not recorded" when the artifact carries no physics block', () => {
    const indicator = indicatorOf(scenario());
    expect(indicator.status).toBe('unmeasured');
    expect(indicator.valueKey).toBe('trust.unmeasured');
  });

  it('reports "not recorded" when physics is explicitly null', () => {
    const indicator = indicatorOf(scenario({ physics: null }));
    expect(indicator.status).toBe('unmeasured');
    expect(indicator.valueKey).toBe('trust.unmeasured');
  });

  it('shows how many of the seven invariants were computed', () => {
    const indicator = indicatorOf(scenario({ physics: partial() }));
    expect(indicator.briefKey).toBe('trust.physics.counted');
    expect(indicator.briefParams).toEqual({ done: 5, total: 7 });
  });

  it('renders "N of 7" from the counted params', () => {
    const indicator = indicatorOf(scenario({ physics: partial() }));
    const template = ru['physics.counted'];
    const rendered = template
      .replace('{done}', String(indicator.briefParams?.done))
      .replace('{total}', String(indicator.briefParams?.total));
    expect(rendered).toBe('5 из 7');
  });

  it('stays unmeasured while the check is incomplete', () => {
    const indicator = indicatorOf(scenario({ physics: partial() }));
    expect(indicator.status).toBe('unmeasured');
    expect(indicator.valueKey).toBe('trust.physics.partial');
    expect(indicator.spoken).toBe(true);
  });

  it('lists the skipped invariants with their reason', () => {
    const indicator = indicatorOf(scenario({ physics: partial() }));
    expect(indicator.detailKey).toBe('trust.physics.skipped');
    expect(indicator.detailParams?.invariants).toBe(
      'INJECTION_RESPONSE, MATERIAL_BALANCE'
    );
  });

  it('calls a full clean check measured', () => {
    const indicator = indicatorOf(scenario({ physics: physics() }));
    expect(indicator.status).toBe('neutral');
    expect(indicator.valueKey).toBe('trust.physics.clean');
    expect(indicator.detailKey).toBeUndefined();
  });

  it('treats BHP_LIMIT flags as warnings, never as blocking', () => {
    const indicator = indicatorOf(
      scenario({ physics: physics({ warning_count: 4, admissible: true }) })
    );
    expect(indicator.status).not.toBe('danger');
    expect(indicator.status).toBe('neutral');
    expect(indicator.valueKey).toBe('trust.physics.clean');
    expect(indicator.detailKey).toBe('trust.physics.warnings');
    expect(indicator.detailParams).toEqual({ count: 4 });
  });

  it('flags blocking violations as a danger', () => {
    const indicator = indicatorOf(
      scenario({
        physics: physics({ blocking_count: 2, admissible: false, warning_count: 1 })
      })
    );
    expect(indicator.status).toBe('danger');
    expect(indicator.valueKey).toBe('trust.physics.blocking');
    expect(indicator.valueParams).toEqual({ count: 2 });
  });

  it('keeps BHP_LIMIT out of the blocking count entirely', () => {
    const warningOnly = physics({ warning_count: 9, blocking_count: 0 });
    expect(warningOnly.warning_invariants).toEqual(['BHP_LIMIT']);
    const indicator = indicatorOf(scenario({ physics: warningOnly }));
    expect(indicator.status).toBe('neutral');
  });

  it('has every physics key in both languages', () => {
    const keys = [
      'label.physics',
      'physics.counted',
      'physics.partial',
      'physics.skipped',
      'physics.clean',
      'physics.blocking',
      'physics.warnings'
    ];
    for (const key of keys) {
      expect(ru, key).toHaveProperty(key);
      expect(en, key).toHaveProperty(key);
    }
  });

  it('accepts a scenarios file that carries a physics block', () => {
    const file = {
      scenarios: [scenario({ physics: partial() })],
      submitted: 'base'
    };
    expect(isScenariosFile(file)).toBe(true);
  });

  it('accepts a scenarios file with no physics block at all', () => {
    expect(isScenariosFile({ scenarios: [scenario()], submitted: null })).toBe(true);
  });

  it('rejects a physics block that is not shaped like a report', () => {
    const file = {
      scenarios: [{ ...scenario(), physics: { total: 7 } }],
      submitted: null
    };
    expect(isScenariosFile(file)).toBe(false);
  });
});
