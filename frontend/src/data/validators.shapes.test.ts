import { describe, expect, it } from 'vitest';
import {
  isGraphFile,
  isNpvFile,
  isScenariosFile,
  isWellsFile
} from './validators';

const graph = (overrides: Record<string, unknown> = {}) => ({
  window: { start: '2007-01-01', end: '2008-07-01' },
  nodes: [{ id: 'I1', role: 'INJ', group: 'G1', x: 10, y: 10 }],
  edges: [{ injector: 'I1', producer: 'P1', weight: 0.9 }],
  groups: [],
  weight_range: { min: 0.9, max: 0.9 },
  meta: { lag_months: 3, amplitude: 0.2, stability: 0.77, rank: 2, condition_number: 4.25 },
  layout: { size: 100, seed: 1 },
  ...overrides
});

const wells = (overrides: Record<string, unknown> = {}) => ({
  grid: { ni: 10, nj: 12, nk: 6 },
  layers: [{ id: 1, k_min: 1, k_max: 3 }],
  wells: [{ id: 'W1', i: 2, j: 3, completions: [[1, 2]], layers: [1] }],
  ...overrides
});

const summary = {
  injection_limits: 0,
  liquid_limits: 0,
  production_floors: 0,
  watercut_limits: 0,
  well_outages: 0,
  infrastructure: 0,
  years: [],
  outage_wells: [],
  empty: true
};

const entry = (overrides: Record<string, unknown> = {}) => ({
  id: 'final',
  config_hash: 'a'.repeat(64),
  converged: true,
  self_consistent: true,
  is_submitted: true,
  npv_methodology: null,
  constraints: summary,
  ...overrides
});

const scenarios = (overrides: Record<string, unknown> = {}) => ({
  submitted: 'final',
  scenarios: [entry()],
  ...overrides
});

describe('isGraphFile', () => {
  it('accepts a well-formed file', () => {
    expect(isGraphFile(graph())).toBe(true);
  });

  it('accepts a graph with no edges so an empty window stays renderable', () => {
    expect(isGraphFile(graph({ edges: [] }))).toBe(true);
  });

  it('rejects an empty node list', () => {
    expect(isGraphFile(graph({ nodes: [] }))).toBe(false);
  });

  it('rejects an edge weight that is not a number', () => {
    expect(
      isGraphFile(graph({ edges: [{ injector: 'I1', producer: 'P1', weight: '0.9' }] }))
    ).toBe(false);
  });

  it('rejects a node with a non-numeric coordinate', () => {
    expect(isGraphFile(graph({ nodes: [{ id: 'I1', x: 'left', y: 10 }] }))).toBe(false);
  });

  it('rejects a missing measurement window', () => {
    expect(isGraphFile(graph({ window: undefined }))).toBe(false);
    expect(isGraphFile(graph({ window: { start: '2007-01-01' } }))).toBe(false);
  });
});

describe('isWellsFile', () => {
  it('accepts a well-formed file', () => {
    expect(isWellsFile(wells())).toBe(true);
  });

  it('accepts an empty well list so the empty state can render', () => {
    expect(isWellsFile(wells({ wells: [] }))).toBe(true);
  });

  it('rejects a well with a non-numeric grid index', () => {
    expect(
      isWellsFile(wells({ wells: [{ id: 'W1', i: NaN, j: 3, completions: [], layers: [] }] }))
    ).toBe(false);
  });

  it('rejects a missing grid', () => {
    expect(isWellsFile(wells({ grid: undefined }))).toBe(false);
  });
});

describe('isNpvFile', () => {
  it('accepts a well-formed file including negative contributions', () => {
    expect(
      isNpvFile({
        npv_methodology: -30,
        wells: [{ well: 'W1', pre_tax: -30, with_allocated_tax: -25 }],
        total: { pre_tax: -30, with_allocated_tax: -25 }
      })
    ).toBe(true);
  });

  it('rejects an empty well list so a blank ranking is not shown as ready', () => {
    expect(
      isNpvFile({ npv_methodology: 0, wells: [], total: { pre_tax: 0, with_allocated_tax: 0 } })
    ).toBe(false);
  });

  it('rejects a missing totals block', () => {
    expect(
      isNpvFile({
        npv_methodology: 1,
        wells: [{ well: 'W1', pre_tax: 1, with_allocated_tax: 2 }]
      })
    ).toBe(false);
  });
});

describe('isScenariosFile', () => {
  it('accepts a well-formed index and an empty library', () => {
    expect(isScenariosFile(scenarios())).toBe(true);
    expect(isScenariosFile(scenarios({ scenarios: [] }))).toBe(true);
  });

  it('rejects an entry without constraints', () => {
    expect(isScenariosFile(scenarios({ scenarios: [entry({ constraints: undefined })] }))).toBe(
      false
    );
  });

  it('rejects an entry whose id is not a string', () => {
    expect(
      isScenariosFile(scenarios({ scenarios: [entry({ id: 7 })] }))
    ).toBe(false);
  });
});
