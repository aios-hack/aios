import { describe, expect, it } from 'vitest';
import { isGraphFile, isNpvFile, isTimelineFile, isWellsFile } from './validators';

describe('validators reject hostile payloads', () => {
  it('rejects a graph whose nodes are not an array', () => {
    expect(isGraphFile({ nodes: 'broken', edges: null })).toBe(false);
  });

  it('rejects an npv row with a non-string well id', () => {
    expect(
      isNpvFile({
        wells: [{ well: 42, pre_tax: 1, with_allocated_tax: 2 }],
        total: { pre_tax: 1, with_allocated_tax: 2 }
      })
    ).toBe(false);
  });

  it('rejects NaN amounts', () => {
    expect(
      isNpvFile({
        wells: [{ well: 'W1', pre_tax: Number.NaN, with_allocated_tax: 2 }],
        total: { pre_tax: 1, with_allocated_tax: 2 }
      })
    ).toBe(false);
  });

  it('rejects a timeline step without wells', () => {
    expect(isTimelineFile({ steps: [{ control_step: 0, date: '2007-01-01' }] })).toBe(false);
  });

  it('rejects a wells grid with non-positive extent', () => {
    expect(isWellsFile({ grid: { ni: -1, nj: 5, nk: 2 }, layers: [], wells: [] })).toBe(false);
  });
});
