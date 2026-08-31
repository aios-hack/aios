import { describe, expect, it } from 'vitest';
import type { GraphFile } from '../../api/types';
import {
  CHRONO_SORTS,
  UNGROUPED,
  buildRows,
  groupByWell,
  sortRows,
  ungroupedCount,
  type ChronoRow
} from './sortRows';

const graph = (): GraphFile =>
  ({
    window: { start: '2007-01-01', end: '2007-02-01' },
    nodes: [],
    edges: [],
    groups: [
      { id: 'G1', wells: ['2', '5'] },
      { id: 'G2', wells: ['10'] }
    ],
    weight_range: { min: 0, max: 1 },
    meta: {},
    layout: { size: 100, seed: 1 }
  }) as unknown as GraphFile;

const npv = new Map<string, number>([
  ['2', 10],
  ['5', 900],
  ['10', -50]
]);

const watercut = new Map<string, number>([
  ['2', 0.2],
  ['5', 0.8],
  ['10', 0.5]
]);

const wells = (rows: readonly ChronoRow[]): string[] => rows.map((row) => row.well);

describe('CHRONO_SORTS', () => {
  it('offers the same sorts as the rest of the history views', () => {
    expect(CHRONO_SORTS).toEqual(['well', 'group', 'npv', 'watercut']);
  });
});

describe('groupByWell', () => {
  it('inverts the graph groups into a lookup by well', () => {
    expect(groupByWell(graph())).toEqual(
      new Map([
        ['2', 'G1'],
        ['5', 'G1'],
        ['10', 'G2']
      ])
    );
  });

  it('knows nothing when the graph is missing', () => {
    expect(groupByWell(null).size).toBe(0);
  });
});

describe('buildRows', () => {
  it('joins the wells to the facts the matrix colours by', () => {
    const rows = buildRows(['2', '33'], groupByWell(graph()), npv, watercut);
    expect(rows).toEqual([
      { well: '2', group: 'G1', npv: 10, watercut: 0.2 },
      { well: '33', group: UNGROUPED, npv: undefined, watercut: undefined }
    ]);
  });

  it('leaves the facts undefined when only the well list is known', () => {
    const rows = buildRows(['7'], new Map(), new Map());
    expect(rows[0]).toEqual({
      well: '7',
      group: UNGROUPED,
      npv: undefined,
      watercut: undefined
    });
  });
});

describe('sortRows', () => {
  const rows = buildRows(['10', '2', '33', '5'], groupByWell(graph()), npv, watercut);

  it('orders wells by number, not by string', () => {
    expect(wells(sortRows(rows, 'well'))).toEqual(['2', '5', '10', '33']);
  });

  it('keeps a group together and leaves the ungrouped wells last', () => {
    expect(wells(sortRows(rows, 'group'))).toEqual(['2', '5', '10', '33']);
  });

  it('puts the richest well first and the unmeasured ones last', () => {
    expect(wells(sortRows(rows, 'npv'))).toEqual(['5', '2', '10', '33']);
  });

  it('puts the wettest well first and the unmeasured ones last', () => {
    expect(wells(sortRows(rows, 'watercut'))).toEqual(['5', '10', '2', '33']);
  });

  it('breaks ties by well number so the order never wobbles', () => {
    const tied = buildRows(
      ['9', '3', '21'],
      new Map(),
      new Map([
        ['9', 1],
        ['3', 1],
        ['21', 1]
      ])
    );
    expect(wells(sortRows(tied, 'npv'))).toEqual(['3', '9', '21']);
  });

  it('never mutates the rows it was given', () => {
    const original = wells(rows);
    sortRows(rows, 'npv');
    expect(wells(rows)).toEqual(original);
  });

  it('sorts an empty matrix into an empty matrix', () => {
    expect(sortRows([], 'group')).toEqual([]);
  });
});

describe('ungroupedCount', () => {
  it('counts only the wells the graph never placed', () => {
    const rows = buildRows(['2', '33', '41'], groupByWell(graph()), npv);
    expect(ungroupedCount(rows)).toBe(2);
    expect(ungroupedCount([])).toBe(0);
  });
});
