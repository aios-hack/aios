import { describe, expect, it } from 'vitest';
import type { TimelineStep, TimelineWellRow } from '../api/types';
import { eventMarks, fieldEvents, yearTicks } from './events';

const row = (
  well: string,
  overrides: Partial<TimelineWellRow> = {}
): TimelineWellRow => ({
  well,
  availability: 'AVAILABLE',
  role: 'PROD',
  operating_status: 'OPEN',
  setpoint: 50,
  liquid_rate: 40,
  injection_rate: 0,
  bhp: 90,
  watercut: 0.4,
  fact_to_target: 0.9,
  cumulative_liquid: 100,
  ...overrides
});

const step = (k: number, wells: TimelineWellRow[]): TimelineStep => ({
  control_step: k,
  date: `${2007 + Math.floor(k / 12)}-${String((k % 12) + 1).padStart(2, '0')}-01`,
  terminal: false,
  field: {
    production: 1000,
    injection: 900,
    compensation: 0.8,
    npv_cumulative: 100 * k,
    active_wells: wells.length
  },
  wells
});

const still = Array.from({ length: 5 }, (_, k) =>
  step(k, [row('P1'), row('I1', { role: 'INJ', injection_rate: 120, liquid_rate: 0 })])
);

describe('fieldEvents on a bundle that never changes state', () => {
  it('finds nothing when role, availability and status stand still', () => {
    expect(fieldEvents(still)).toEqual([]);
  });

  it('produces no marks, not a mark with zero count', () => {
    expect(eventMarks(fieldEvents(still))).toEqual([]);
  });

  it('finds nothing in a single step, because there is no neighbour to compare with', () => {
    expect(fieldEvents(still.slice(0, 1))).toEqual([]);
  });
});

describe('fieldEvents on a bundle that moves', () => {
  const moving = [
    step(0, [
      row('P1'),
      row('P2', { availability: 'NOT_COMMISSIONED', operating_status: 'SHUT' }),
      row('P3')
    ]),
    step(1, [
      row('P1', { role: 'INJ', injection_rate: 130, liquid_rate: 0 }),
      row('P2'),
      row('P3')
    ]),
    step(2, [
      row('P1', { role: 'INJ', injection_rate: 130, liquid_rate: 0 }),
      row('P2'),
      row('P3', { operating_status: 'SHUT' })
    ])
  ];

  it('reads a commissioning off the availability change', () => {
    expect(fieldEvents(moving)).toContainEqual({
      step: 1,
      well: 'P2',
      type: 'COMMISSIONED'
    });
  });

  it('reads a switch to injection off the role change', () => {
    expect(fieldEvents(moving)).toContainEqual({
      step: 1,
      well: 'P1',
      type: 'ROLE_CHANGE'
    });
  });

  it('reads a shutdown off the operating status change', () => {
    expect(fieldEvents(moving)).toContainEqual({ step: 2, well: 'P3', type: 'SHUT' });
  });

  it('groups the marks by step and counts the wells behind each', () => {
    const marks = eventMarks(fieldEvents(moving));
    expect(marks.map((mark) => mark.step)).toEqual([1, 2]);
    expect(marks[0].count).toBe(2);
    expect(marks[0].types.sort()).toEqual(['COMMISSIONED', 'ROLE_CHANGE']);
    expect(marks[1].count).toBe(1);
  });

  it('ignores a well that the previous step did not carry', () => {
    const appeared = [step(0, [row('P1')]), step(1, [row('P1'), row('P9')])];
    expect(fieldEvents(appeared)).toEqual([]);
  });
});

describe('yearTicks', () => {
  it('takes one tick per year from the step dates, not from a constant', () => {
    const steps = Array.from({ length: 26 }, (_, k) => step(k, [row('P1')]));
    expect(yearTicks(steps)).toEqual([
      { step: 0, year: '2007' },
      { step: 12, year: '2008' },
      { step: 24, year: '2009' }
    ]);
  });

  it('has no ticks for no steps', () => {
    expect(yearTicks([])).toEqual([]);
  });
});
