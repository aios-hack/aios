import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { ReactNode } from 'react';
import type {
  TimelineFile,
  TimelineStep,
  TimelineWellRow,
  TraceFile,
  WellsFile
} from '../../api/types';
import { dictionaries } from '../../i18n/dictionaries';
import { I18nProvider } from '../../i18n/I18nContext';
import { TimelineProvider } from '../../state/TimelineContext';
import { FieldMap } from '../FieldMap';
import { Timeline } from '../Timeline/Timeline';
import { WellCard } from './WellCard';

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
    <TimelineProvider>{node}</TimelineProvider>
  </I18nProvider>
);

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
  '/data/trace.json': traceFixture
};

const rowFor = (container: HTMLElement, well: string): HTMLElement => {
  const row = container.querySelector(`tr[data-well-id="${well}"]`);
  expect(row).not.toBeNull();
  return row as HTMLElement;
};

const openFromTable = async (well: string) => {
  const view = render(
    withProviders(
      <>
        <Timeline />
        <WellCard />
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
    fireEvent.click(screen.getByRole('button', { name: ru['wellcard.close'] }));
    await waitFor(() => {
      expect(screen.queryByText(cardTitle('11'))).toBeNull();
    });
  });

  const openFromMap = async (): Promise<{ well: SVGElement }> => {
    mockFetch({ ...stepsPayloads, '/data/wells.json': wellsFixture });
    const { container } = render(
      withProviders(
        <>
          <FieldMap />
          <WellCard />
        </>
      )
    );
    await waitFor(() => expect(container.querySelectorAll('[data-well-id]')).toHaveLength(1));
    return { well: container.querySelector('[data-well-id="11"]') as SVGElement };
  };

  it('moves focus into the dialog and back to the map well on escape', async () => {
    const { well } = await openFromMap();
    well.focus();
    fireEvent.click(well);
    const dialog = await screen.findByRole('dialog');
    await waitFor(() => expect(document.activeElement).toBe(dialog));
    fireEvent.keyDown(window, { key: 'Escape' });
    await waitFor(() => expect(screen.queryByRole('dialog')).toBeNull());
    expect(document.activeElement).toBe(well);
  });

  it('opens from a map well click and highlights the well', async () => {
    const { well } = await openFromMap();
    fireEvent.click(well);
    expect(screen.getByText(cardTitle('11'))).toBeTruthy();
    expect(param('factToTarget')).toContain('140');
    expect(well.getAttribute('data-selected')).toBe('true');
  });
});
