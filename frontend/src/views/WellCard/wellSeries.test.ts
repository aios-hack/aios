import { describe, expect, it } from 'vitest';
import type { TimelineFile, TimelineWellRow } from '../../api/types';
import { buildWellSeries } from './wellSeries';

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
