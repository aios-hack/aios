import { describe, expect, it } from 'vitest';
import type { WellRow } from './levels';
import {
  decisionAmount,
  decisionVerb,
  isNumericWellKey,
  sortWellRows,
  WELL_SORT_KEYS,
  type WellSortKey
} from './wellSorting';

const row = (
  well: string,
  decision: string,
  inputs: Record<string, number>,
  constraint: string | null = null,
  rule = 'R1'
): WellRow => ({
  well,
  group: 'G1',
  decision,
  rule,
  inputs,
  constraint,
  color: null
});

const INPUTS = (limit: number, inj: number, liq: number) => ({
  group_limit_m3_per_day: limit,
  injection_rate_m3_per_day: inj,
  liquid_rate_m3_per_day: liq
});

describe('decision strings split into a verb and a number', () => {
  it('separates the two halves the table shows in different columns', () => {
    expect(decisionVerb('SET_RATE 164.7')).toBe('SET_RATE');
    expect(decisionAmount('SET_RATE 164.7')).toBeCloseTo(164.7);
    expect(decisionVerb('SET_LRAT 0')).toBe('SET_LRAT');
    expect(decisionAmount('SET_LRAT 0')).toBe(0);
  });

  it('reports a missing number rather than inventing one', () => {
    expect(decisionAmount('SHUT')).toBeNull();
    expect(decisionVerb('SHUT')).toBe('SHUT');
  });
});

describe('sorting the executor table', () => {
  const rows: WellRow[] = [
    row('10', 'SET_LRAT 50', INPUTS(800, 0, 50), 'OUTAGE', 'R2'),
    row('2', 'SET_RATE 160', INPUTS(800, 160, 0)),
    row('33', 'SET_RATE 90', INPUTS(800, 90, 0), 'KNS_LIMIT')
  ];

  it('offers a key for every column the table renders', () => {
    expect(WELL_SORT_KEYS).toHaveLength(8);
    expect(new Set(WELL_SORT_KEYS).size).toBe(8);
  });

  it('orders wells by number, not by string', () => {
    expect(sortWellRows(rows, 'well', 'asc').map((r) => r.well)).toEqual(['2', '10', '33']);
    expect(sortWellRows(rows, 'well', 'desc').map((r) => r.well)).toEqual(['33', '10', '2']);
  });

  it('sorts by the decision amount, both directions', () => {
    expect(sortWellRows(rows, 'amount', 'asc').map((r) => r.well)).toEqual(['10', '33', '2']);
    expect(sortWellRows(rows, 'amount', 'desc').map((r) => r.well)).toEqual(['2', '33', '10']);
  });

  it('sorts by each input column independently, tied rows reversing with the direction', () => {
    expect(sortWellRows(rows, 'injection', 'desc').map((r) => r.well)).toEqual([
      '2',
      '33',
      '10'
    ]);
    expect(sortWellRows(rows, 'liquid', 'desc').map((r) => r.well)).toEqual([
      '10',
      '33',
      '2'
    ]);
    expect(sortWellRows(rows, 'liquid', 'asc').map((r) => r.well)).toEqual([
      '2',
      '33',
      '10'
    ]);
  });

  it('breaks ties by well number so the order never wobbles', () => {
    const tied = [
      row('9', 'SET_RATE 100', INPUTS(800, 100, 0)),
      row('3', 'SET_RATE 100', INPUTS(800, 100, 0)),
      row('21', 'SET_RATE 100', INPUTS(800, 100, 0))
    ];
    expect(sortWellRows(tied, 'amount', 'asc').map((r) => r.well)).toEqual(['3', '9', '21']);
    expect(sortWellRows(tied, 'groupLimit', 'asc').map((r) => r.well)).toEqual([
      '3',
      '9',
      '21'
    ]);
  });

  it('keeps rows without a constraint last when sorting ascending', () => {
    const plain = sortWellRows(
      [row('1', 'SET_RATE 1', INPUTS(1, 1, 0)), row('2', 'SET_RATE 2', INPUTS(1, 2, 0), 'OUTAGE')],
      'constraint',
      'asc'
    );
    expect(plain.map((r) => r.well)).toEqual(['2', '1']);
  });

  it('never mutates the rows it was given', () => {
    const original = rows.map((r) => r.well);
    sortWellRows(rows, 'amount', 'desc');
    expect(rows.map((r) => r.well)).toEqual(original);
  });

  it('marks exactly the measured columns as numeric', () => {
    const numeric = WELL_SORT_KEYS.filter((key: WellSortKey) => isNumericWellKey(key));
    expect(numeric).toEqual(['amount', 'groupLimit', 'injection', 'liquid']);
  });
});
