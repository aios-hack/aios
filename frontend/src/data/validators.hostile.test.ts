import { describe, expect, it } from 'vitest';
import {
  isGraphFile,
  isNpvFile,
  isScenariosFile,
  isTimelineFile,
  isTraceFile,
  isWellsFile
} from './validators';

const graph = (overrides: Record<string, unknown> = {}) => ({
  window: { start: '2007-01-01', end: '2008-07-01' },
  nodes: [{ id: 'I1', role: 'INJ', group: 'G1', x: 10, y: 10 }],
  edges: [{ injector: 'I1', producer: 'P1', weight: 0.9 }],
  groups: [{ id: 'G1', wells: ['I1'] }],
  weight_range: { min: 0.1, max: 0.9 },
  meta: { lag_months: 3, amplitude: 0.2, stability: 0.77, rank: 2, condition_number: 4.25 },
  layout: { size: 100, seed: 1 },
  ...overrides
});

const step = (overrides: Record<string, unknown> = {}) => ({
  control_step: 0,
  date: '2007-01-01',
  terminal: false,
  field: {
    production: 1,
    injection: 1,
    compensation: 1,
    npv_cumulative: 1,
    active_wells: 1
  },
  wells: [],
  ...overrides
});

const timeline = (overrides: Record<string, unknown> = {}) => ({
  model: 'Model_Z',
  t0: '2007-01-01',
  n_control_dates: 225,
  n_intervals: 224,
  wells: ['W1'],
  steps: [step()],
  ...overrides
});

const wells = (overrides: Record<string, unknown> = {}) => ({
  grid: { ni: 10, nj: 12, nk: 6 },
  layers: [{ id: 1, k_min: 1, k_max: 3 }],
  wells: [{ id: 'W1', i: 2, j: 3, completions: [[1, 2]], layers: [1] }],
  ...overrides
});

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

describe('validators reject payloads that would crash a consumer', () => {
  it('rejects a graph without the weight range the edge layer scales by', () => {
    expect(isGraphFile(graph({ weight_range: undefined }))).toBe(false);
    expect(isGraphFile(graph({ weight_range: { min: 0.1 } }))).toBe(false);
    expect(isGraphFile(graph({ weight_range: { min: 0.1, max: '0.9' } }))).toBe(false);
  });

  it('rejects a graph whose groups cannot be walked for members', () => {
    expect(isGraphFile(graph({ groups: undefined }))).toBe(false);
    expect(isGraphFile(graph({ groups: [{ id: 'G1' }] }))).toBe(false);
    expect(isGraphFile(graph({ groups: [{ id: 'G1', wells: [7] }] }))).toBe(false);
  });

  it('rejects a graph node whose role is outside the drawn set', () => {
    expect(isGraphFile(graph({ nodes: [{ id: 'I1', role: 'PUMP', group: null, x: 1, y: 2 }] }))).toBe(
      false
    );
  });

  it('rejects Infinity coordinates that would break the layout fit', () => {
    expect(
      isGraphFile(graph({ nodes: [{ id: 'I1', role: 'INJ', group: null, x: Infinity, y: 2 }] }))
    ).toBe(false);
  });

  it('rejects a trace bucket that is a string rather than a record list', () => {
    expect(isTraceFile({ W1: { '0': 'SET_RATE' } })).toBe(false);
  });

  it('rejects a trace record whose inputs table cannot be enumerated', () => {
    expect(isTraceFile({ W1: { '0': [{ rule: 'R4', decision: 'd' }] } })).toBe(false);
    expect(
      isTraceFile({ W1: { '0': [{ rule: 'R4', decision: 'd', inputs: null }] } })
    ).toBe(false);
  });

  it('rejects a trace record whose input value is not a finite number', () => {
    expect(
      isTraceFile({ W1: { '0': [{ rule: 'R4', decision: 'd', inputs: { a: 'x' } }] } })
    ).toBe(false);
    expect(
      isTraceFile({
        W1: { '0': [{ rule: 'R4', decision: 'd', inputs: { a: Number.NaN } }] }
      })
    ).toBe(false);
  });

  it('rejects a trace carrying a polluting key instead of a well id', () => {
    expect(isTraceFile(JSON.parse('{"__proto__": {"0": []}}'))).toBe(false);
    expect(isTraceFile(JSON.parse('{"constructor": {"0": []}}'))).toBe(false);
    expect(
      isTraceFile(
        JSON.parse('{"W1": {"0": [{"rule":"R","decision":"d","inputs":{"__proto__":1}}]}}')
      )
    ).toBe(false);
  });

  it('leaves the object prototype untouched after reading a hostile trace', () => {
    isTraceFile(JSON.parse('{"__proto__": {"polluted": 1}}'));
    expect(({} as Record<string, unknown>).polluted).toBeUndefined();
  });

  it('rejects well layers that are not numbers the filter can match', () => {
    expect(isWellsFile(wells({ wells: [{ id: 'W1', i: 1, j: 2, completions: [], layers: ['1'] }] }))).toBe(
      false
    );
    expect(isWellsFile(wells({ layers: [{ id: '1', k_min: 1, k_max: 3 }] }))).toBe(false);
    expect(isWellsFile(wells({ layers: [{ k_min: 1, k_max: 3 }] }))).toBe(false);
  });

  it('rejects a completion that is not an [i, j] pair', () => {
    expect(
      isWellsFile(wells({ wells: [{ id: 'W1', i: 1, j: 2, completions: [[1]], layers: [1] }] }))
    ).toBe(false);
    expect(
      isWellsFile(wells({ wells: [{ id: 'W1', i: 1, j: 2, completions: [['a', 2]], layers: [1] }] }))
    ).toBe(false);
  });

  it('rejects a timeline without the interval count the editor bounds by', () => {
    expect(isTimelineFile(timeline({ n_intervals: undefined }))).toBe(false);
    expect(isTimelineFile(timeline({ n_intervals: -1 }))).toBe(false);
    expect(isTimelineFile(timeline({ n_intervals: Number.NaN }))).toBe(false);
  });

  it('rejects a step without the terminal flag the scale reads', () => {
    expect(isTimelineFile(timeline({ steps: [step({ terminal: undefined })] }))).toBe(false);
    expect(isTimelineFile(timeline({ steps: [step({ terminal: 'yes' })] }))).toBe(false);
  });

  it('rejects a compensation band that cannot be drawn', () => {
    expect(isTimelineFile(timeline({ field_norms: { compensation: { min: 0.95 } } }))).toBe(
      false
    );
    expect(
      isTimelineFile(timeline({ field_norms: { compensation: { min: 0.95, max: Infinity } } }))
    ).toBe(false);
  });

  it('accepts a timeline that simply omits the optional band', () => {
    expect(isTimelineFile(timeline())).toBe(true);
    expect(isTimelineFile(timeline({ field_norms: undefined }))).toBe(true);
  });

  it('rejects a scenario whose constraint counters cannot be summed', () => {
    expect(isScenariosFile({ scenarios: [{ id: 'a', constraints: {} }] })).toBe(false);
    expect(
      isScenariosFile({
        scenarios: [
          {
            id: 'a',
            constraints: {
              injection_limits: '0',
              liquid_limits: 0,
              production_floors: 0,
              watercut_limits: 0,
              well_outages: 0,
              infrastructure: 0
            }
          }
        ]
      })
    ).toBe(false);
  });

  it('rejects an npv total of Infinity that would poison every share', () => {
    expect(
      isNpvFile({
        wells: [{ well: 'W1', pre_tax: 1, with_allocated_tax: 2 }],
        total: { pre_tax: Infinity, with_allocated_tax: 2 }
      })
    ).toBe(false);
  });
});

const scenarioEntry = (overrides: Record<string, unknown> = {}) => ({
  id: 'final',
  config_hash: 'a'.repeat(64),
  converged: true,
  self_consistent: true,
  is_submitted: true,
  npv_methodology: null,
  constraints: {
    injection_limits: 0,
    liquid_limits: 0,
    production_floors: 0,
    watercut_limits: 0,
    well_outages: 0,
    infrastructure: 0,
    years: [],
    outage_wells: [],
    empty: true
  },
  ...overrides
});

const scenarios = (overrides: Record<string, unknown> = {}) => ({
  submitted: 'final',
  scenarios: [scenarioEntry()],
  ...overrides
});

const npv = (overrides: Record<string, unknown> = {}) => ({
  npv_methodology: 100,
  wells: [{ well: 'W1', pre_tax: 1, with_allocated_tax: 2 }],
  total: { pre_tax: 1, with_allocated_tax: 2 },
  ...overrides
});

describe('validators cover the fields consumers dereference', () => {
  it('rejects a timeline without the well column list the history views map over', () => {
    expect(isTimelineFile(timeline({ wells: undefined }))).toBe(false);
    expect(isTimelineFile(timeline({ wells: 'W1' }))).toBe(false);
    expect(isTimelineFile(timeline({ wells: [1, 2] }))).toBe(false);
  });

  it('rejects a timeline missing the model and t0 the header states', () => {
    expect(isTimelineFile(timeline({ model: undefined }))).toBe(false);
    expect(isTimelineFile(timeline({ t0: 7 }))).toBe(false);
  });

  it('rejects a timeline whose control-date count is not a finite number', () => {
    expect(isTimelineFile(timeline({ n_control_dates: undefined }))).toBe(false);
    expect(isTimelineFile(timeline({ n_control_dates: -1 }))).toBe(false);
  });

  it('rejects a provenance that is not a string the notice would trim', () => {
    expect(
      isTimelineFile(timeline({ meta: { kind: 'timeline', provenance: 42 } }))
    ).toBe(false);
    expect(isTimelineFile(timeline({ meta: { provenance: 'run' } }))).toBe(false);
    expect(isTimelineFile(timeline({ meta: 'synthetic' }))).toBe(false);
  });

  it('accepts a timeline that omits the optional metadata block', () => {
    expect(isTimelineFile(timeline({ meta: undefined }))).toBe(true);
  });

  it('rejects a notice that is not a string the notice would render', () => {
    expect(
      isTimelineFile(
        timeline({ meta: { kind: 'timeline', provenance: 'synthetic-demo', notice_ru: 7 } })
      )
    ).toBe(false);
  });

  it('rejects a trace whose metadata block is malformed', () => {
    expect(isTraceFile({ __meta__: { kind: 'trace', provenance: 7 } })).toBe(false);
    expect(isTraceFile({ __meta__: { kind: 'trace', provenance: 'run' } })).toBe(true);
  });

  it('rejects an npv file without the methodology figure the library states', () => {
    expect(isNpvFile(npv({ npv_methodology: undefined }))).toBe(false);
    expect(isNpvFile(npv({ npv_methodology: Number.NaN }))).toBe(false);
  });

  it('rejects a graph whose meta lacks the connectivity diagnostics', () => {
    expect(isGraphFile(graph({ meta: undefined }))).toBe(false);
    expect(isGraphFile(graph({ meta: { lag_months: 3 } }))).toBe(false);
    expect(
      isGraphFile(
        graph({
          meta: {
            lag_months: 3,
            amplitude: 0.2,
            stability: 0.77,
            rank: 2,
            condition_number: Infinity
          }
        })
      )
    ).toBe(false);
  });

  it('rejects a graph without the layout block', () => {
    expect(isGraphFile(graph({ layout: undefined }))).toBe(false);
    expect(isGraphFile(graph({ layout: { size: 100 } }))).toBe(false);
  });

  it('rejects a scenario missing the flags the trust board reads', () => {
    expect(isScenariosFile(scenarios({ scenarios: [scenarioEntry({ converged: undefined })] }))).toBe(
      false
    );
    expect(
      isScenariosFile(scenarios({ scenarios: [scenarioEntry({ self_consistent: 'yes' })] }))
    ).toBe(false);
    expect(
      isScenariosFile(scenarios({ scenarios: [scenarioEntry({ is_submitted: undefined })] }))
    ).toBe(false);
    expect(
      isScenariosFile(scenarios({ scenarios: [scenarioEntry({ config_hash: undefined })] }))
    ).toBe(false);
  });

  it('rejects a constraints summary the library cannot branch on', () => {
    expect(
      isScenariosFile(
        scenarios({
          scenarios: [
            scenarioEntry({
              constraints: {
                injection_limits: 0,
                liquid_limits: 0,
                production_floors: 0,
                watercut_limits: 0,
                well_outages: 0,
                infrastructure: 0,
                years: [],
                outage_wells: []
              }
            })
          ]
        })
      )
    ).toBe(false);
    expect(
      isScenariosFile(
        scenarios({
          scenarios: [
            scenarioEntry({
              constraints: {
                injection_limits: 0,
                liquid_limits: 0,
                production_floors: 0,
                watercut_limits: 0,
                well_outages: 0,
                infrastructure: 0,
                years: ['2007'],
                outage_wells: [],
                empty: true
              }
            })
          ]
        })
      )
    ).toBe(false);
  });

  it('rejects a well row whose role is outside the declared set', () => {
    const row = (overrides: Record<string, unknown>) => ({
      well: 'W1',
      availability: 'AVAILABLE',
      role: 'PROD',
      operating_status: 'OPEN',
      setpoint: 1,
      liquid_rate: 1,
      injection_rate: 0,
      bhp: 1,
      watercut: null,
      fact_to_target: null,
      cumulative_liquid: 1,
      ...overrides
    });
    expect(isTimelineFile(timeline({ steps: [step({ wells: [row({})] })] }))).toBe(true);
    expect(
      isTimelineFile(timeline({ steps: [step({ wells: [row({ role: 'PRDO' })] })] }))
    ).toBe(false);
    expect(
      isTimelineFile(timeline({ steps: [step({ wells: [row({ role: 'inj' })] })] }))
    ).toBe(false);
    expect(
      isTimelineFile(timeline({ steps: [step({ wells: [row({ role: '' })] })] }))
    ).toBe(false);
    for (const role of ['INJ', 'PROD', 'NONE']) {
      expect(isTimelineFile(timeline({ steps: [step({ wells: [row({ role })] })] }))).toBe(
        true
      );
    }
  });

  it('rejects a well row whose availability or operating status is outside the declared set', () => {
    const row = (overrides: Record<string, unknown>) => ({
      well: 'W1',
      availability: 'AVAILABLE',
      role: 'PROD',
      operating_status: 'OPEN',
      setpoint: 1,
      liquid_rate: 1,
      injection_rate: 0,
      bhp: 1,
      watercut: null,
      fact_to_target: null,
      cumulative_liquid: 1,
      ...overrides
    });
    expect(
      isTimelineFile(timeline({ steps: [step({ wells: [row({ availability: 'READY' })] })] }))
    ).toBe(false);
    expect(
      isTimelineFile(
        timeline({ steps: [step({ wells: [row({ availability: 'NOT_COMMISSIONED' })] })] })
      )
    ).toBe(true);
    expect(
      isTimelineFile(
        timeline({ steps: [step({ wells: [row({ operating_status: 'CLOSED' })] })] })
      )
    ).toBe(false);
    expect(
      isTimelineFile(timeline({ steps: [step({ wells: [row({ operating_status: 'SHUT' })] })] }))
    ).toBe(true);
  });

  it('rejects a well row whose explanation is not text', () => {
    const row = (overrides: Record<string, unknown>) => ({
      well: 'W1',
      availability: 'AVAILABLE',
      role: 'PROD',
      operating_status: 'OPEN',
      setpoint: 1,
      liquid_rate: 1,
      injection_rate: 0,
      bhp: 1,
      watercut: null,
      fact_to_target: null,
      cumulative_liquid: 1,
      ...overrides
    });
    expect(
      isTimelineFile(timeline({ steps: [step({ wells: [row({ explanation: 7 })] })] }))
    ).toBe(false);
    expect(
      isTimelineFile(timeline({ steps: [step({ wells: [row({ explanation: null })] })] }))
    ).toBe(true);
    expect(
      isTimelineFile(timeline({ steps: [step({ wells: [row({ explanation: 'shut in' })] })] }))
    ).toBe(true);
  });

  it('rejects a scenario index whose submitted pointer is not a string or null', () => {
    expect(isScenariosFile(scenarios({ submitted: 7 }))).toBe(false);
    expect(isScenariosFile(scenarios({ submitted: null }))).toBe(true);
  });

  it('rejects an npv methodology that is not a number on a scenario entry', () => {
    expect(
      isScenariosFile(scenarios({ scenarios: [scenarioEntry({ npv_methodology: '1' })] }))
    ).toBe(false);
    expect(
      isScenariosFile(scenarios({ scenarios: [scenarioEntry({ npv_methodology: 12 })] }))
    ).toBe(true);
  });
});
