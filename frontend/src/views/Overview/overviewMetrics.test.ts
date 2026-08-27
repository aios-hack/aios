import { describe, expect, it } from 'vitest';
import type { TimelineStep, TimelineWellRow } from '../../api/types';
import {
  averageFactToTarget,
  averageWatercut,
  overviewMetrics,
  shutWellCount
} from './overviewMetrics';

const well = (over: Partial<TimelineWellRow>): TimelineWellRow => ({
  well: 'P1',
  availability: 'AVAILABLE',
  role: 'PROD',
  operating_status: 'OPEN',
  setpoint: 50,
  liquid_rate: 40,
  injection_rate: 0,
  bhp: 90,
  watercut: 0.5,
  fact_to_target: 0.9,
  cumulative_liquid: 100,
  ...over
});

const step = (
  index: number,
  field: Partial<TimelineStep['field']>,
  wells: TimelineWellRow[] = [well({})]
): TimelineStep => ({
  control_step: index,
  date: `2007-${String((index % 12) + 1).padStart(2, '0')}-01`,
  terminal: false,
  field: {
    production: 100,
    injection: 80,
    compensation: 1,
    npv_cumulative: 1000,
    active_wells: 50,
    ...field
  },
  wells
});

describe('overview derived readings', () => {
  it('averages watercut over producers only, since injectors have none', () => {
    const current = step(0, {}, [
      well({ well: 'P1', watercut: 0.6 }),
      well({ well: 'P2', watercut: 0.8 }),
      well({ well: 'I1', role: 'INJ', watercut: null })
    ]);
    expect(averageWatercut(current)).toBeCloseTo(0.7);
  });

  it('reports no watercut when no producer carries a reading', () => {
    expect(averageWatercut(step(0, {}, [well({ role: 'INJ', watercut: null })]))).toBeNull();
  });

  it('averages fact against target across the whole fund', () => {
    const current = step(0, {}, [
      well({ well: 'P1', fact_to_target: 0.8 }),
      well({ well: 'I1', role: 'INJ', fact_to_target: 1 })
    ]);
    expect(averageFactToTarget(current)).toBeCloseTo(0.9);
  });

  it('counts the wells standing shut', () => {
    const current = step(0, {}, [
      well({ well: 'P1', operating_status: 'SHUT' }),
      well({ well: 'P2', operating_status: 'OPEN' }),
      well({ well: 'P3', operating_status: 'SHUT' })
    ]);
    expect(shutWellCount(current)).toBe(2);
  });
});

describe('overviewMetrics', () => {
  it('returns nothing without steps', () => {
    expect(overviewMetrics([], 0, null)).toEqual([]);
  });

  it('covers every metric the overview page draws', () => {
    const keys = overviewMetrics([step(0, {})], 0, null).map((metric) => metric.key);
    expect(keys).toEqual([
      'npv',
      'compensation',
      'production',
      'injection',
      'watercut',
      'factToTarget',
      'activeWells',
      'shutWells'
    ]);
  });

  it('states where a series started, ended and how far it swung', () => {
    const steps = [
      step(0, { production: 100 }),
      step(1, { production: 180 }),
      step(2, { production: 60 })
    ];
    const production = overviewMetrics(steps, 2, null)[2];

    expect(production.first).toBe(100);
    expect(production.last).toBe(60);
    expect(production.peak).toBe(180);
    expect(production.trough).toBe(60);
  });

  it('measures the change against the step before, and leaves the first one open', () => {
    const steps = [step(0, { production: 100 }), step(1, { production: 140 })];
    expect(overviewMetrics(steps, 1, null)[2].delta).toBe(40);
    expect(overviewMetrics(steps, 0, null)[2].delta).toBeNull();
  });

  it('ignores gaps in a series when reading its bounds', () => {
    const steps = [
      step(0, { production: null }),
      step(1, { production: 120 }),
      step(2, { production: null })
    ];
    const production = overviewMetrics(steps, 2, null)[2];

    expect(production.first).toBe(120);
    expect(production.peak).toBe(120);
    expect(production.current).toBeNull();
  });

  it('carries the compensation band only on compensation', () => {
    const band = { min: 0.95, max: 1.15 };
    const metrics = overviewMetrics([step(0, {})], 0, band);
    const withBand = metrics.filter((metric) => metric.band !== null).map((metric) => metric.key);
    expect(withBand).toEqual(['compensation']);
  });
});
