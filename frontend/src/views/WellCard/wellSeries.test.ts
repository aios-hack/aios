import { describe, expect, it } from 'vitest';
import type { TimelineFile, TimelineWellRow } from '../../api/types';
import { buildWellSeries, wellRowAt } from './wellSeries';

const row = (overrides: Partial<TimelineWellRow>): TimelineWellRow => ({
  well: 'W1',
  availability: 'AVAILABLE',
  role: 'PROD',
  operating_status: 'OPEN',
  setpoint: 10,
  liquid_rate: 10,
  injection_rate: 0,
  bhp: 100,
  watercut: 0.2,
  fact_to_target: 1,
  cumulative_liquid: 0,
  ...overrides
});

const timelineOf = (rows: TimelineWellRow[][], wells: string[]): TimelineFile => ({
  model: 'demo',
  t0: '2007-01-01',
  n_control_dates: rows.length,
  n_intervals: rows.length - 1,
  wells,
  steps: rows.map((wellRows, index) => ({
    control_step: index,
    date: `2007-0${index + 1}-01`,
    terminal: index === rows.length - 1,
    field: {
      production: 1,
      injection: 1,
      compensation: 1,
      npv_cumulative: 1,
      active_wells: wellRows.length
    },
    wells: wellRows
  }))
});

describe('buildWellSeries', () => {
  it('reads the row that belongs to the well, not the one sitting in its column', () => {
    const timeline = timelineOf(
      [
        [row({ well: 'W1', liquid_rate: 10 }), row({ well: 'W2', liquid_rate: 98 })],
        [row({ well: 'W2', liquid_rate: 99 }), row({ well: 'W1', liquid_rate: 11 })]
      ],
      ['W1', 'W2']
    );
    const [rate] = buildWellSeries(timeline, 'W1');
    expect(rate.values).toEqual([10, 11]);
  });

  it('reports a missing row rather than borrowing a neighbour value', () => {
    const timeline = timelineOf(
      [
        [row({ well: 'W1', liquid_rate: 10 }), row({ well: 'W2', liquid_rate: 98 })],
        [row({ well: 'W2', liquid_rate: 99 })]
      ],
      ['W1', 'W2']
    );
    const [rate] = buildWellSeries(timeline, 'W1');
    expect(rate.values).toEqual([10, null]);
  });


  it('returns one value per step for each of the three quantities', () => {
    const timeline = timelineOf(
      [[row({ liquid_rate: 10 })], [row({ liquid_rate: 20 })], [row({ liquid_rate: 30 })]],
      ['W1']
    );
    const series = buildWellSeries(timeline, 'W1');
    expect(series.map((entry) => entry.key)).toEqual(['rate', 'watercut', 'bhp']);
    for (const entry of series) {
      expect(entry.values).toHaveLength(timeline.steps.length);
    }
  });

  it('reads the injection rate for a well that spends its life injecting', () => {
    const timeline = timelineOf(
      [
        [row({ role: 'INJ', injection_rate: 150, liquid_rate: 0, watercut: null })],
        [row({ role: 'INJ', injection_rate: 160, liquid_rate: 0, watercut: null })]
      ],
      ['W1']
    );
    const [rate] = buildWellSeries(timeline, 'W1');
    expect(rate.values).toEqual([150, 160]);
    expect(rate.injector).toBe(true);
  });

  it('keeps a converted well on the side it spent most of its life', () => {
    const timeline = timelineOf(
      [
        [row({ role: 'PROD', liquid_rate: 40 })],
        [row({ role: 'PROD', liquid_rate: 30 })],
        [row({ role: 'INJ', injection_rate: 90, liquid_rate: 0 })]
      ],
      ['W1']
    );
    const [rate] = buildWellSeries(timeline, 'W1');
    expect(rate.injector).toBe(false);
    expect(rate.values).toEqual([40, 30, 90]);
  });

  it('passes a missing watercut through as a gap, never as zero', () => {
    const timeline = timelineOf(
      [[row({ watercut: null })], [row({ watercut: 0.5 })]],
      ['W1']
    );
    const [, watercut] = buildWellSeries(timeline, 'W1');
    expect(watercut.values).toEqual([null, 0.5]);
  });

  it('reports no series at all for a well outside the fund', () => {
    const timeline = timelineOf([[row({})]], ['W1']);
    expect(buildWellSeries(timeline, 'W404')).toEqual([]);
  });

  it('leaves a gap where a step carries no row for the well', () => {
    const timeline = timelineOf([[row({})], []], ['W1']);
    const [rate] = buildWellSeries(timeline, 'W1');
    expect(rate.values).toEqual([10, null]);
  });
});

describe('wellRowAt', () => {
  const first = row({ well: 'W1' });
  const second = row({ well: 'W2', liquid_rate: 42 });
  const step = timelineOf([[first, second]], ['W1', 'W2']).steps[0];

  it('reads the row straight from its column when the order holds', () => {
    expect(wellRowAt(step, 'W1', 0)).toBe(first);
    expect(wellRowAt(step, 'W2', 1)).toBe(second);
  });

  it('falls back to a scan when the column does not line up', () => {
    expect(wellRowAt(step, 'W2', 0)).toBe(second);
    expect(wellRowAt(step, 'W1', 7)).toBe(first);
    expect(wellRowAt(step, 'W1', -1)).toBe(first);
  });

  it('reports a missing well and a missing step as no row', () => {
    expect(wellRowAt(step, 'W9', 0)).toBeNull();
    expect(wellRowAt(null, 'W1', 0)).toBeNull();
  });
});
