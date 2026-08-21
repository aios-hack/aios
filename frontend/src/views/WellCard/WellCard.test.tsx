import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { ReactNode } from 'react';
import type {
  GraphFile,
  ScenariosFile,
  TimelineFile,
  TimelineStep,
  TimelineWellRow,
  TraceFile,
  WellsFile
} from '../../api/types';
import { dictionaries } from '../../i18n/dictionaries';
import { useT } from '../../i18n/I18nContext';
import { I18nProvider } from '../../i18n/I18nContext';
import { PlaybackProvider, usePlayback } from '../../state/PlaybackContext';
import { ScenarioProvider } from '../../state/ScenarioContext';
import { TimelineProvider, useTimeline } from '../../state/TimelineContext';
import { ConsoleInspector } from '../../ui/Inspector';
import type { InspectorContext } from '../../ui/Inspector';
import { ViewStatus } from '../../ui/ViewStatus';
import { FieldProjection } from '../FieldProjection';
import { StepControls } from '../Timeline/StepControls';
import { WellsTable } from '../Timeline/WellsTable';

const StepsTestView = () => {
  const t = useT();
  const { timeline, stepIndex, selectedWell, selectWell } = useTimeline();
  const { playing, selectStep, onStep, togglePlay } = usePlayback();

  if (timeline.status === 'loading') {
    return <ViewStatus kind="loading" title={t('steps.loading')} />;
  }
  if (timeline.status === 'error') {
    return <ViewStatus kind="error" title={t('steps.error')} hint={t('steps.errorHint')} />;
  }

  const steps = timeline.data.steps;
  const current = Math.min(stepIndex, steps.length - 1);
  const step = steps[current];

  return (
    <section>
      <StepControls
        steps={steps}
        stepIndex={current}
        playing={playing}
        onSelect={selectStep}
        onStep={onStep}
        onTogglePlay={togglePlay}
      />
      <WellsTable wells={step.wells} selectedWell={selectedWell} onSelectWell={selectWell} />
    </section>
  );
};

const { ru } = dictionaries;

const wellRow = (
  overrides: Partial<TimelineWellRow> & { well: string }
): TimelineWellRow => ({
  availability: 'AVAILABLE',
  role: 'PROD',
  operating_status: 'OPEN',
  setpoint: 50,
  liquid_rate: 70,
  injection_rate: 0,
  bhp: 91,
  watercut: 0.5,
  fact_to_target: 1.4,
  cumulative_liquid: 2100,
  ...overrides
});

const makeStep = (k: number, wells: TimelineWellRow[]): TimelineStep => ({
  control_step: k,
  date: `2007-0${k + 1}-01`,
  terminal: false,
  field: {
    production: 2000 + k,
    injection: 1500 + k,
    compensation: 0.75,
    npv_cumulative: 1000 * (k + 1),
    active_wells: 2
  },
  wells
});

const timelineFixture: TimelineFile = {
  model: 'Model_Z',
  t0: '2007-01-01',
  n_control_dates: 2,
  n_intervals: 1,
  wells: ['11', '12', '14'],
  steps: [
    makeStep(0, [
      wellRow({ well: '11' }),
      wellRow({ well: '12', operating_status: 'SHUT', fact_to_target: null }),
      wellRow({
        well: '14',
        availability: 'NOT_COMMISSIONED',
        role: 'NONE',
        operating_status: 'SHUT',
        setpoint: 0,
        liquid_rate: 0,
        bhp: 0,
        watercut: 0,
        fact_to_target: null,
        cumulative_liquid: 0,
        explanation: 'Скважина ещё не введена в фонд'
      })
    ]),
    makeStep(1, [
      wellRow({
        well: '11',
        liquid_rate: 80,
        fact_to_target: 1.6,
        cumulative_liquid: 4300
      }),
      wellRow({ well: '12', operating_status: 'SHUT', fact_to_target: null }),
      wellRow({
        well: '14',
        availability: 'NOT_COMMISSIONED',
        role: 'NONE',
        operating_status: 'SHUT',
        setpoint: 0,
        liquid_rate: 0,
        bhp: 0,
        watercut: 0,
        fact_to_target: null,
        cumulative_liquid: 0
      })
    ])
  ]
};

const traceFixture: TraceFile = {
  '11': {
    '0': [
      {
        rule: 'R1',
        inputs: { watercut: 0.83, liquid_rate: 72 },
        decision: 'SET_LRAT 50.0'
      }
    ]
  }
};

const graphFixture: GraphFile = {
  window: { start: '2007-01-01', end: '2009-01-01' },
  nodes: [
    { id: '11', role: 'PROD', group: 'G1', x: 10, y: 10 },
    { id: '12', role: 'INJ', group: 'G1', x: 20, y: 14 },
    { id: '13', role: 'INJ', group: 'G2', x: 40, y: 30 },
    { id: '14', role: 'PROD', group: null, x: 60, y: 50 }
  ],
  edges: [
    { injector: '12', producer: '11', weight: 0.42 },
    { injector: '13', producer: '11', weight: 0.91 }
  ],
  groups: [
    { id: 'G1', wells: ['11', '12'] },
    { id: 'G2', wells: ['13'] }
  ],
  weight_range: { min: 0.42, max: 0.91 },
  meta: {
    lag_months: 2,
    amplitude: 0.3,
    stability: 0.99,
    rank: 2,
    condition_number: 3.1
  },
  layout: { size: 100, seed: 20070101 }
};

const wellsFixture: WellsFile = {
  grid: { ni: 10, nj: 12, nk: 6 },
  layers: [
    { id: 1, k_min: 1, k_max: 3 },
    { id: 2, k_min: 5, k_max: 6 }
  ],
  wells: [{ id: '11', i: 2, j: 3, completions: [[1, 2]], layers: [1] }]
};

const withProviders = (node: ReactNode) => (
  <I18nProvider>
    <TimelineProvider>
      <PlaybackProvider>{node}</PlaybackProvider>
    </TimelineProvider>
  </I18nProvider>
);

const withScenarioProviders = (node: ReactNode) => (
  <I18nProvider>
    <ScenarioProvider>
      <TimelineProvider>
        <PlaybackProvider>{node}</PlaybackProvider>
      </TimelineProvider>
    </ScenarioProvider>
  </I18nProvider>
);

const scenariosFixture: ScenariosFile = {
  submitted: 'final',
  scenarios: [
    {
      id: 'final',
      config_hash: 'a'.repeat(64),
      converged: true,
      self_consistent: true,
      is_submitted: true,
      npv_methodology: 123456789,
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
      final_npv: { npv_rub: 123456789, run_id: 'run-42' },
      run_validation_clean: true
    }
  ]
};

const mockFetch = (payloads: Record<string, unknown>) => {
  vi.stubGlobal(
    'fetch',
    vi.fn((url: string) =>
      Promise.resolve({ ok: true, json: () => Promise.resolve(payloads[url]) })
    )
  );
};

const stepsPayloads = {
  '/data/timeline.json': timelineFixture,
  '/data/trace.json': traceFixture,
  '/data/graph.json': graphFixture
};

const rowFor = (container: HTMLElement, well: string): HTMLElement => {
  const row = container.querySelector(`tr[data-well-id="${well}"]`);
  expect(row).not.toBeNull();
  return row as HTMLElement;
};

const noopInspector = { scenarioContext: null, onCloseScenario: () => undefined };

const openFromTable = async (well: string) => {
  const view = render(
    withProviders(
      <>
        <StepsTestView />
        <ConsoleInspector {...noopInspector} />
      </>
    )
  );
  await waitFor(() =>
    expect(view.container.querySelectorAll('tbody tr')).toHaveLength(3)
  );
  fireEvent.click(rowFor(view.container, well));
  return view;
};

const cardTitle = (well: string) => ru['wellcard.title'].replace('{well}', well);

const param = (name: string): string =>
  document.querySelector(`[data-param="${name}"]`)?.textContent ?? '';

beforeEach(() => {
  localStorage.clear();
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe('WellCard', () => {
  it('opens with step parameters when a table row is clicked', async () => {
    mockFetch(stepsPayloads);
    const { container } = await openFromTable('11');
    expect(screen.getByText(cardTitle('11'))).toBeTruthy();
    expect(param('factToTarget')).toContain('140');
    expect(param('cumulative')).toContain('2');
    expect(param('bhp')).toContain('91');
    expect(rowFor(container, '11').getAttribute('data-selected')).toBe('true');
  });

  it('shows a dash for fact to target on a shut well', async () => {
    mockFetch(stepsPayloads);
    await openFromTable('12');
    expect(param('factToTarget')).toBe('—');
    expect(param('status')).toBe(ru['steps.status.SHUT']);
  });

  it('renders trace records with rule, inputs and decision', async () => {
    mockFetch(stepsPayloads);
    await openFromTable('11');
    await screen.findByText('R1');
    expect(screen.getByText('SET_LRAT 50.0')).toBeTruthy();
    expect(screen.getByText('watercut')).toBeTruthy();
    expect(screen.getByText('0,83')).toBeTruthy();
    expect(screen.getByText('72')).toBeTruthy();
  });

  it('shows the empty trace message when no rules fired', async () => {
    mockFetch(stepsPayloads);
    await openFromTable('12');
    await screen.findByText(ru['wellcard.decision.empty']);
  });

  it('falls back to the unavailable explanation message', async () => {
    mockFetch(stepsPayloads);
    await openFromTable('11');
    expect(screen.getByText(ru['wellcard.explanation.empty'])).toBeTruthy();
  });

  it('renders the explanation text when present', async () => {
    mockFetch(stepsPayloads);
    await openFromTable('14');
    expect(screen.getByText('Скважина ещё не введена в фонд')).toBeTruthy();
    expect(screen.queryByText(ru['wellcard.explanation.empty'])).toBeNull();
  });

  it('updates the card when the step changes and closes on demand', async () => {
    mockFetch(stepsPayloads);
    const { container } = await openFromTable('11');
    expect(param('actual')).toContain('70');
    const slider = container.querySelector('input[type="range"]') as HTMLInputElement;
    fireEvent.change(slider, { target: { value: '1' } });
    expect(param('actual')).toContain('80');
    expect(param('factToTarget')).toContain('160');
    fireEvent.click(screen.getByRole('button', { name: ru['inspector.close'] }));
    await waitFor(() => {
      expect(screen.queryByText(cardTitle('11'))).toBeNull();
    });
  });

  const openFromMap = async (): Promise<{ well: SVGElement }> => {
    mockFetch({
      ...stepsPayloads,
      '/data/wells.json': wellsFixture
    });
    const { container } = render(
      withProviders(
        <>
          <FieldProjection />
          <ConsoleInspector {...noopInspector} />
        </>
      )
    );
    await waitFor(() =>
      expect(container.querySelectorAll('[data-well-id]')).toHaveLength(
        graphFixture.nodes.length
      )
    );
    return { well: container.querySelector('[data-well-id="11"]') as SVGElement };
  };

  it('closes on escape and returns focus to the map well that opened it', async () => {
    const { well } = await openFromMap();
    well.focus();
    fireEvent.click(well);
    await screen.findByTestId('inspector');
    fireEvent.keyDown(window, { key: 'Escape' });
    await waitFor(() => expect(screen.queryByTestId('inspector')).toBeNull());
    expect(document.activeElement).toBe(well);
  });

  it('opens from a map well click and highlights the well', async () => {
    const { well } = await openFromMap();
    fireEvent.click(well);
    expect(screen.getByText(cardTitle('11'))).toBeTruthy();
    expect(param('factToTarget')).toContain('140');
    expect(well.getAttribute('data-selected')).toBe('true');
  });

  it('is a side panel, not a modal dialog, and traps no focus', async () => {
    const { well } = await openFromMap();
    fireEvent.click(well);
    const panel = await screen.findByTestId('inspector');
    expect(panel.tagName).toBe('ASIDE');
    expect(panel.getAttribute('aria-modal')).toBeNull();
    expect(panel.getAttribute('role')).toBeNull();
    expect(screen.queryByRole('dialog')).toBeNull();
    expect(document.querySelector('.inspector-backdrop')).toBeNull();
    expect(document.activeElement).not.toBe(panel);
    expect(panel.contains(document.activeElement)).toBe(false);
  });

  it('keeps the scene in the document and clickable while a well is selected', async () => {
    mockFetch(stepsPayloads);
    const { container } = await openFromTable('11');
    await screen.findByTestId('inspector');
    expect(container.querySelectorAll('tbody tr[data-well-id]')).toHaveLength(3);
    fireEvent.click(rowFor(container, '12'));
    await waitFor(() => expect(screen.getByText(cardTitle('12'))).toBeTruthy());
    expect(rowFor(container, '12').getAttribute('data-selected')).toBe('true');
  });

  it('lists the well group and the lambda measurement window', async () => {
    mockFetch(stepsPayloads);
    await openFromTable('11');
    await screen.findByTestId('wellcard-connectivity');
    expect(screen.getByTestId('wellcard-group').textContent).toContain('G1');
    expect(screen.getByTestId('wellcard-window').textContent).toContain('01.01.2007');
    expect(screen.getByTestId('wellcard-window').textContent).toContain('01.01.2009');
  });

  it('shows a well without a group explicitly instead of dropping it', async () => {
    mockFetch(stepsPayloads);
    await openFromTable('14');
    await screen.findByTestId('wellcard-connectivity');
    expect(screen.getByTestId('wellcard-group').textContent).toContain(
      ru['wellcard.group.none']
    );
  });

  it('builds the neighbour list from graph.json sorted by lambda', async () => {
    mockFetch(stepsPayloads);
    await openFromTable('11');
    const list = await screen.findByTestId('wellcard-neighbours');
    const wells = [...list.querySelectorAll('[data-neighbour]')].map((node) =>
      node.getAttribute('data-neighbour')
    );
    expect(wells).toEqual(['13', '12']);
    expect(list.textContent).toContain('0.910');
    expect(list.textContent).toContain('0.420');
  });

  it('moves the selection when a neighbour is clicked', async () => {
    mockFetch(stepsPayloads);
    const { container } = await openFromTable('11');
    const list = await screen.findByTestId('wellcard-neighbours');
    fireEvent.click(list.querySelector('[data-neighbour="12"]') as HTMLElement);
    await waitFor(() => expect(screen.getByText(cardTitle('12'))).toBeTruthy());
    expect(rowFor(container, '12').getAttribute('data-selected')).toBe('true');
  });

  it('reports a well missing from the influence graph', async () => {
    mockFetch({
      ...stepsPayloads,
      '/data/graph.json': {
        ...graphFixture,
        nodes: graphFixture.nodes.filter((node) => node.id !== '11'),
        edges: [],
        groups: []
      }
    });
    await openFromTable('11');
    await screen.findByText(ru['wellcard.neighbours.absent']);
  });

  it('renders scenario details when the inspector context is a scenario', async () => {
    mockFetch({ '/data/scenarios.json': scenariosFixture });
    const context: InspectorContext = { kind: 'scenario', scenarioId: 'final' };
    render(
      withScenarioProviders(
        <ConsoleInspector scenarioContext={context} onCloseScenario={() => undefined} />
      )
    );
    const inspector = await screen.findByTestId('inspector');
    expect(inspector.getAttribute('aria-modal')).toBeNull();
    await screen.findByTestId('scenario-inspector');
    expect(screen.getByText('run-42')).toBeTruthy();
    expect(screen.getByText(ru['inspector.scenario.validationClean'])).toBeTruthy();
  });
});
