import { describe, expect, it } from 'vitest';
import type { TimelineStep } from '../../api/types';
import { fieldMetrics } from './fieldMetrics';

const step = (
  index: number,
  field: Partial<TimelineStep['field']>
): TimelineStep => ({
  control_step: index,
  date: `2007-${String(index + 1).padStart(2, '0')}-01`,
  terminal: false,
  field: {
    production: 100,
    injection: 80,
    compensation: 1,
    npv_cumulative: 1000,
    active_wells: 50,
    ...field
  },
  wells: []
});

describe('fieldMetrics', () => {
  it('returns nothing when there are no steps', () => {
    expect(fieldMetrics([], 0, null)).toEqual([]);
  });

  it('reads the value at the requested step and the one before it', () => {
    const steps = [
      step(0, { production: 100 }),
      step(1, { production: 120 }),
      step(2, { production: 90 })
    ];
    const production = fieldMetrics(steps, 2, null)[0];

    expect(production.current).toBe(90);
    expect(production.previous).toBe(120);
    expect(production.delta).toBe(-30);
    expect(production.trend).toBe('down');
  });

  it('leaves the first step without a delta because nothing precedes it', () => {
    const production = fieldMetrics([step(0, {}), step(1, {})], 0, null)[0];

    expect(production.previous).toBeNull();
    expect(production.delta).toBeNull();
    expect(production.trend).toBe('flat');
  });

  it('calls a change below a tenth of a percent flat rather than a direction', () => {
    const steps = [step(0, { production: 100000 }), step(1, { production: 100001 })];
    expect(fieldMetrics(steps, 1, null)[0].trend).toBe('flat');
  });

  it('reports the delta as a share of the previous value', () => {
    const steps = [step(0, { production: 200 }), step(1, { production: 250 })];
    expect(fieldMetrics(steps, 1, null)[0].deltaRatio).toBeCloseTo(0.25);
  });

  it('places compensation against its norm band', () => {
    const band = { min: 0.95, max: 1.15 };
    const inside = fieldMetrics([step(0, { compensation: 1 })], 0, band)[2];
    const below = fieldMetrics([step(0, { compensation: 0.5 })], 0, band)[2];
    const above = fieldMetrics([step(0, { compensation: 1.5 })], 0, band)[2];

    expect(inside.bandPosition).toBe('inside');
    expect(below.bandPosition).toBe('below');
    expect(above.bandPosition).toBe('above');
  });

  it('leaves metrics without a band unplaced', () => {
    expect(fieldMetrics([step(0, {})], 0, null)[0].bandPosition).toBeNull();
  });

  it('survives a step index beyond the series', () => {
    const steps = [step(0, { production: 100 }), step(1, { production: 140 })];
    expect(fieldMetrics(steps, 99, null)[0].current).toBe(140);
  });

  it('carries a missing reading through as null instead of zero', () => {
    const steps = [step(0, { production: null }), step(1, { production: null })];
    const production = fieldMetrics(steps, 1, null)[0];

    expect(production.current).toBeNull();
    expect(production.delta).toBeNull();
  });
});
