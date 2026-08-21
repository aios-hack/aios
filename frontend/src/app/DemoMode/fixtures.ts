import type { DemoScriptFile, TimelineFile, TimelineWellRow, TraceFile } from '../../api/types';

const WELLS = ['1', '2', '3'];
const STEP_COUNT = 40;

const wellRow = (well: string, k: number): TimelineWellRow => ({
  well,
  availability: well === '3' && k < 10 ? 'NOT_COMMISSIONED' : 'AVAILABLE',
  role: well === '2' && k >= 20 ? 'INJ' : 'PROD',
  operating_status: 'OPEN',
  setpoint: 50,
  liquid_rate: 40 + k,
  injection_rate: 0,
  bhp: 90 + k,
  watercut: 0.3,
  fact_to_target: 0.9,
  cumulative_liquid: 100 * (k + 1)
});

export const timelineFixture: TimelineFile = {
  model: 'Model_Z',
  t0: '2007-01-01',
  n_control_dates: STEP_COUNT,
  n_intervals: STEP_COUNT - 1,
  wells: WELLS,
  steps: Array.from({ length: STEP_COUNT }, (_, k) => ({
    control_step: k,
    date: `${2007 + Math.floor(k / 12)}-${String((k % 12) + 1).padStart(2, '0')}-01`,
    terminal: k === STEP_COUNT - 1,
    field: {
      production: 2000 + k,
      injection: 1500 + k,
      compensation: 0.75,
      npv_cumulative: 1000 * (k + 1),
      active_wells: WELLS.length
    },
    wells: WELLS.map((well) => wellRow(well, k))
  }))
};

export const traceFixture: TraceFile = {
  '1': {
    '0': [{ rule: 'R4', inputs: { compensation: 1.2 }, decision: 'SET_RATE 130' }],
    '30': [{ rule: 'R1', inputs: { watercut: 0.3 }, decision: 'SET_RATE 90' }]
  }
};

export const scriptFixture: DemoScriptFile = {
  meta: { kind: 'demo-script', provenance: 'synthetic-demo', synthetic: true },
  frames: [
    { step: 0, scene: 'projection', t: 0, well: null, event: null, hold_ms: 40 },
    {
      step: 0,
      scene: 'projection',
      t: 1,
      well: null,
      event: { type: 'MORPH' },
      hold_ms: 40
    },
    {
      step: 30,
      scene: 'chronomap',
      well: '1',
      event: { type: 'RULE_FIRED', well: '1', rule: 'R1' },
      hold_ms: 40
    }
  ],
  total_ms: 120
};
