import { describe, expect, it } from 'vitest';
import { isTimelineFile } from './validators';

const wellRow = () => ({
  well: '11',
  availability: 'AVAILABLE',
  role: 'PROD',
  operating_status: 'OPEN',
  setpoint: 50,
  liquid_rate: 70,
  injection_rate: 0,
  bhp: 91,
  watercut: 0.5,
  fact_to_target: 1.4,
  cumulative_liquid: 2100
});

const step = (overrides: Record<string, unknown> = {}) => ({
  control_step: 0,
  date: '2007-01-01',
  terminal: false,
  field: {
    production: 2000,
    injection: 1500,
    compensation: 0.75,
    npv_cumulative: 1000,
    active_wells: 2
  },
  wells: [wellRow()],
  ...overrides
});

const timeline = (overrides: Record<string, unknown> = {}) => ({
  model: 'Model_Z',
  t0: '2007-01-01',
  n_control_dates: 1,
  n_intervals: 0,
  wells: ['11'],
  steps: [step()],
  ...overrides
});




describe('isTimelineFile', () => {
  it('accepts a well-formed file', () => {
    expect(isTimelineFile(timeline())).toBe(true);
  });

  it('accepts a terminal step whose observed month is null', () => {
    expect(
      isTimelineFile(
        timeline({
          steps: [
            step({
              terminal: true,
              field: {
                production: null,
                injection: null,
                compensation: null,
                npv_cumulative: 1000,
                active_wells: 2
              },
              wells: [{ ...wellRow(), watercut: null, fact_to_target: null }]
            })
          ]
        })
      )
    ).toBe(true);
  });

  it('rejects an empty steps array so an empty run is not treated as ready', () => {
    expect(isTimelineFile(timeline({ steps: [] }))).toBe(false);
  });

  it('rejects a cumulative npv that is null rather than a number', () => {
    expect(
      isTimelineFile(
        timeline({
          steps: [
            step({
              field: {
                production: 1,
                injection: 1,
                compensation: 1,
                npv_cumulative: null,
                active_wells: 2
              }
            })
          ]
        })
      )
    ).toBe(false);
  });

  it('rejects a well row whose rate is a numeric string', () => {
    expect(
      isTimelineFile(timeline({ steps: [step({ wells: [{ ...wellRow(), bhp: '91' }] })] }))
    ).toBe(false);
  });

  it('rejects an infinite rate', () => {
    expect(
      isTimelineFile(
        timeline({ steps: [step({ wells: [{ ...wellRow(), liquid_rate: Infinity }] })] })
      )
    ).toBe(false);
  });

  it('rejects a missing date key', () => {
    const broken = step();
    delete (broken as Record<string, unknown>).date;
    expect(isTimelineFile(timeline({ steps: [broken] }))).toBe(false);
  });

  it('rejects a steps array larger than the safety cap', () => {
    expect(isTimelineFile(timeline({ steps: new Array(200001).fill(step()) }))).toBe(false);
  });

  it('rejects null and a bare array', () => {
    expect(isTimelineFile(null)).toBe(false);
    expect(isTimelineFile([])).toBe(false);
  });
});
