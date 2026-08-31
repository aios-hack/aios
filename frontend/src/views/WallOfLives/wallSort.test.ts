import { describe, expect, it } from 'vitest';
import { UNGROUPED } from '../shared/wellFacts';
import {
  WALL_SORTS,
  buildWallRows,
  sortWallRows,
  ungroupedWells,
  type WallRow
} from './wallSort';

const groups = new Map<string, string>([
  ['2', 'G1'],
  ['10', 'G2']
]);

const npv = new Map<string, number>([
  ['2', 50],
  ['10', 900]
]);

const watercut = new Map<string, number>([
  ['2', 0.9],
  ['10', 0.1]
]);

const wells = (rows: readonly WallRow[]): string[] => rows.map((row) => row.well);

describe('WALL_SORTS', () => {
  it('offers the same sorts as the rest of the history views', () => {
    expect(WALL_SORTS).toEqual(['well', 'group', 'npv', 'watercut']);
  });
});

describe('buildWallRows', () => {
  it('joins each well to its group, npv and watercut', () => {
    const rows = buildWallRows(['2', '10', '33'], groups, npv, watercut);
    expect(rows).toEqual([
      { well: '2', group: 'G1', npv: 50, watercut: 0.9 },
      { well: '10', group: 'G2', npv: 900, watercut: 0.1 },
      { well: '33', group: UNGROUPED, npv: undefined, watercut: undefined }
    ]);
  });

  it('builds nothing from no wells', () => {
    expect(buildWallRows([], groups, npv)).toEqual([]);
  });
});

describe('sortWallRows', () => {
  const rows = buildWallRows(['10', '2', '33'], groups, npv, watercut);

  it('orders wells by number, not by string', () => {
    expect(wells(sortWallRows(rows, 'well'))).toEqual(['2', '10', '33']);
  });

  it('groups wells together and leaves the ungrouped ones last', () => {
    expect(wells(sortWallRows(rows, 'group'))).toEqual(['2', '10', '33']);
  });

  it('puts the richest well first and the unmeasured ones last', () => {
    expect(wells(sortWallRows(rows, 'npv'))).toEqual(['10', '2', '33']);
  });

  it('puts the wettest well first and the unmeasured ones last', () => {
    expect(wells(sortWallRows(rows, 'watercut'))).toEqual(['2', '10', '33']);
  });

  it('never mutates the rows it was given', () => {
    const original = wells(rows);
    sortWallRows(rows, 'npv');
    expect(wells(rows)).toEqual(original);
  });
});

describe('ungroupedWells', () => {
  it('names the wells the graph never placed in a group', () => {
    const rows = buildWallRows(['2', '33', '41'], groups, npv);
    expect(ungroupedWells(rows)).toEqual(['33', '41']);
  });

  it('names nobody when every well has a group', () => {
    expect(ungroupedWells(buildWallRows(['2', '10'], groups, npv))).toEqual([]);
  });

  it('names every well when the graph placed nobody', () => {
    const rows = buildWallRows(['2', '10'], new Map(), npv);
    expect(ungroupedWells(rows)).toEqual(['2', '10']);
  });
});
