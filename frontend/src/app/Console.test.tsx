import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { App } from '../App';
import type {
  AblationFile,
  GraphFile,
  NpvFile,
  ScenariosFile,
  TimelineFile,
  TimelineWellRow
} from '../api/types';
import { dictionaries } from '../i18n/dictionaries';
import { I18nProvider } from '../i18n/I18nContext';
import { ConsoleProvider } from '../state/ConsoleContext';
import { PlaybackProvider } from '../state/PlaybackContext';
import { ScenarioProvider } from '../state/ScenarioContext';
import { TimelineProvider } from '../state/TimelineContext';
import { ThemeProvider } from '../theme/ThemeContext';

const { ru } = dictionaries;

const WELLS = ['I1', 'P1', 'P2'];

const wellRow = (well: string, k: number): TimelineWellRow => ({
  well,
  availability: 'AVAILABLE',
  role: well.startsWith('I') ? 'INJ' : 'PROD',
  operating_status: 'OPEN',
  setpoint: 50,
  liquid_rate: well.startsWith('I') ? 0 : 40 + 10 * k,
  injection_rate: well.startsWith('I') ? 120 + k : 0,
  bhp: 90 + k,
  watercut: well.startsWith('I') ? null : 0.3 + 0.1 * k,
  fact_to_target: 0.9,
  cumulative_liquid: 100 * (k + 1)
});

const timelineFixture: TimelineFile = {
  model: 'Model_Z',
  t0: '2007-01-01',
  n_control_dates: 14,
  n_intervals: 13,
  wells: WELLS,
  steps: Array.from({ length: 14 }, (_, k) => ({
    control_step: k,
    date: `${2007 + Math.floor(k / 12)}-${String((k % 12) + 1).padStart(2, '0')}-01`,
    terminal: k === 13,
    field: {
      production: k === 13 ? null : 2000 + k,
      injection: k === 13 ? null : 1500 + k,
      compensation: k === 13 ? null : 0.75,
      npv_cumulative: 1000 * (k + 1),
      active_wells: 3
    },
    wells: WELLS.map((well) => wellRow(well, k))
  }))
};

const graphFixture: GraphFile = {
  window: { start: '2007-01-01', end: '2008-07-01' },
  nodes: [
    { id: 'I1', role: 'INJ', group: 'G1', x: 10, y: 10 },
    { id: 'P1', role: 'PROD', group: 'G1', x: 20, y: 14 },
    { id: 'P2', role: 'PROD', group: 'G2', x: 80, y: 70 }
  ],
  edges: [
    { injector: 'I1', producer: 'P1', weight: 0.9 },
    { injector: 'I1', producer: 'P2', weight: 0.2 }
  ],
  groups: [
    { id: 'G1', wells: ['I1', 'P1'] },
    { id: 'G2', wells: ['P2'] }
  ],
  weight_range: { min: 0.2, max: 0.9 },
  meta: {
    lag_months: 2,
    amplitude: 0.2,
    stability: 0.99,
    rank: 2,
    condition_number: 3.1
  },
  layout: { size: 100, seed: 20070101 }
};

const wellsFixture = {
  grid: { ni: 40, nj: 40, nk: 4 },
  layers: [1, 2],
  wells: [
    { id: 'I1', i: 5, j: 5, layers: [1], completions: [], role: 'INJ' },
    { id: 'P1', i: 12, j: 9, layers: [1], completions: [], role: 'PROD' },
    { id: 'P2', i: 30, j: 24, layers: [2], completions: [], role: 'PROD' }
  ]
};

const npvFixture: NpvFile = {
  wells: [
    { well: 'I1', pre_tax: 10, with_allocated_tax: 8 },
    { well: 'P1', pre_tax: 50, with_allocated_tax: 40 },
    { well: 'P2', pre_tax: 30, with_allocated_tax: 24 }
  ],
  total: { pre_tax: 90, with_allocated_tax: 72 },
  npv_methodology: 72
};

const ablationFixture: AblationFile = {
  npv_total: 90,
  rules: [{ rule: 'R0', enabled: true, delta_npv: 5, share: 0.5 }]
};

const scenariosFixture: ScenariosFile = {
  submitted: 'base',
  scenarios: [
    {
      id: 'base',
      config_hash: 'hash-base',
      converged: true,
      self_consistent: true,
      is_submitted: true,
      npv_methodology: 72,
      constraints: {
        injection_limits: 0,
        liquid_limits: 0,
        production_floors: 0,
        watercut_limits: 0,
        well_outages: 0,
        infrastructure: 0,
        years: [2007],
        outage_wells: [],
        empty: true
      }
    }
  ]
};

const mockFetch = () => {
  vi.stubGlobal(
    'fetch',
    vi.fn((url: string) => {
      const payload = url.includes('graph')
        ? graphFixture
        : url.includes('timeline')
          ? timelineFixture
          : url.includes('wells')
            ? wellsFixture
            : url.includes('ablation')
              ? ablationFixture
              : url.includes('npv')
                ? npvFixture
                : url.includes('scenarios')
                  ? scenariosFixture
                  : {};
      return Promise.resolve({ ok: true, json: () => Promise.resolve(payload) });
    })
  );
};

const renderConsole = () =>
  render(
    <ThemeProvider>
      <I18nProvider>
        <ScenarioProvider>
          <TimelineProvider>
            <PlaybackProvider>
              <ConsoleProvider>
                <App />
              </ConsoleProvider>
            </PlaybackProvider>
          </TimelineProvider>
        </ScenarioProvider>
      </I18nProvider>
    </ThemeProvider>
  );

const navButton = (label: string): HTMLElement => {
  try {
    return screen.getByRole('tab', { name: label });
  } catch {
    return screen.getByRole('button', { name: label });
  }
};

const STEP_COUNT = timelineFixture.steps.length;

const stepPosition = (container: HTMLElement): string =>
  container.querySelector('.time-scale-position')?.textContent ?? '';

const seekTo = (container: HTMLElement, index: number): void => {
  const input = container.querySelector('.time-scale-input') as HTMLInputElement;
  fireEvent.change(input, { target: { value: String(index) } });
};

beforeEach(() => {
  localStorage.clear();
  window.history.replaceState(null, '', window.location.pathname);
  mockFetch();
});

afterEach(() => {
  cleanup();
  window.history.replaceState(null, '', window.location.pathname);
  vi.unstubAllGlobals();
});

describe('console layout', () => {
  it('keeps the time scale in the document in every workspace', async () => {
    renderConsole();
    await screen.findByTestId('time-scale');
    await screen.findByTestId('field-projection-plot');
    expect(screen.getByTestId('time-scale')).toBeTruthy();

    fireEvent.click(navButton(ru['workspace.history']));
    await screen.findByLabelText(ru['chrono.ariaLabel']);
    expect(screen.getByTestId('time-scale')).toBeTruthy();

    fireEvent.click(navButton(ru['workspace.field']));
    await screen.findByTestId('field-projection-plot');
    expect(screen.getByTestId('time-scale')).toBeTruthy();
  });

  it('reaches all four workspaces through the left navigation, none other', async () => {
    renderConsole();
    await screen.findByTestId('time-scale');
    const nav = screen.getByRole('navigation', { name: ru['nav.label'] });
    const items = [...nav.querySelectorAll('button')].map((button) => button.textContent);
    expect(items).toEqual([
      ru['workspace.field'],
      ru['workspace.history'],
      ru['workspace.decisions'],
      ru['workspace.money']
    ]);
  });

  it('renders money content inside the scene area, not below the time axis', async () => {
    renderConsole();
    await screen.findByTestId('time-scale');
    fireEvent.click(navButton(ru['workspace.money']));
    const money = await screen.findByTestId('money-workspace', {}, { timeout: 5000 });
    const scene = screen.getByTestId('console-scene');
    expect(scene.contains(money)).toBe(true);
    const timeaxis = document.querySelector('.console-area-timeaxis');
    expect(timeaxis?.contains(money)).toBe(false);
    expect(money.compareDocumentPosition(timeaxis as Node) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  });

  it('switches workspaces with the number keys, but not while typing', async () => {
    renderConsole();
    await screen.findByTestId('time-scale');
    fireEvent.keyDown(window, { key: '2' });
    await waitFor(() =>
      expect(navButton(ru['workspace.history']).getAttribute('aria-selected')).toBe('true')
    );
    const editable = document.createElement('input');
    document.body.appendChild(editable);
    editable.focus();
    fireEvent.keyDown(editable, { key: '4' });
    expect(navButton(ru['workspace.history']).getAttribute('aria-selected')).toBe('true');
    editable.remove();
  });

  it('has no bottom tab bar and no fund-table toggle left in the console', async () => {
    renderConsole();
    await screen.findByTestId('time-scale');
    expect(document.querySelector('.console-bottom-tabs')).toBeNull();
    expect(screen.queryByTestId('console-steps-toggle')).toBeNull();
  });

  it('reaches the well table from the history workspace instead of a toggle under the scene', async () => {
    renderConsole();
    fireEvent.click(navButton(ru['workspace.history']));
    fireEvent.click(navButton(ru['view.table']));
    await screen.findByTestId('history-table');
  });
});

describe('global step propagation', () => {
  it('moves the chronomap cursor and the well card when the step changes', async () => {
    const { container } = renderConsole();
    await screen.findByTestId('field-projection-plot');

    fireEvent.click(await screen.findByLabelText('P1'));
    await screen.findByTestId('wellcard');
    const cardStep = () =>
      container.querySelector('.wellcard-step')?.textContent ?? '';
    expect(cardStep()).toContain('1');

    seekTo(container, 4);
    await waitFor(() => expect(cardStep()).toContain('5'));

    fireEvent.click(navButton(ru['workspace.history']));
    await screen.findByLabelText(ru['chrono.ariaLabel']);
    expect(
      container.querySelector('.chronomap-cursor')?.getAttribute('data-step')
    ).toBe('4');

    seekTo(container, 7);
    await waitFor(() =>
      expect(
        container.querySelector('.chronomap-cursor')?.getAttribute('data-step')
      ).toBe('7')
    );
    expect(cardStep()).toContain('8');
  });

  it('seeks by clicking the scale itself', async () => {
    const { container } = renderConsole();
    await screen.findByTestId('time-scale-track');
    seekTo(container, STEP_COUNT - 1);
    await waitFor(() => expect(stepPosition(container)).toContain(String(STEP_COUNT)));
  });
});

describe('time axis shape', () => {
  it('offers exactly one draggable control for the step', async () => {
    const { container } = renderConsole();
    await screen.findByTestId('time-scale');
    const axis = container.querySelector('.time-scale') as HTMLElement;
    expect(axis.querySelectorAll('input[type="range"]').length).toBe(1);
    expect(axis.querySelectorAll('.time-scale-input').length).toBe(1);
    expect(screen.getByTestId('time-scale-track')).toBeTruthy();
  });

  it('drags the step through the range input on the track', async () => {
    const { container } = renderConsole();
    await screen.findByTestId('time-scale');
    const input = container.querySelector('.time-scale-input') as HTMLInputElement;
    expect(input.max).toBe(String(STEP_COUNT - 1));
    fireEvent.change(input, { target: { value: '6' } });
    await waitFor(() => expect(stepPosition(container)).toContain('7'));
  });

  it('puts the date above the rail and hides the step counter from sight', async () => {
    const { container } = renderConsole();
    await screen.findByTestId('time-scale');
    const readout = container.querySelector('.time-scale-readout') as HTMLElement;
    const rail = container.querySelector('.time-scale-rail') as HTMLElement;
    expect(readout).toBeTruthy();
    const order = readout.compareDocumentPosition(rail);
    expect(order & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(container.querySelector('.time-scale-position')?.className).toContain(
      'visually-hidden'
    );
  });

  it('glides the cursor only while playing', async () => {
    const { container } = renderConsole();
    await screen.findByTestId('time-scale');
    const track = container.querySelector('.time-scale-track') as HTMLElement;
    expect(track.style.getPropertyValue('--time-scale-glide')).toBe('0ms');
    fireEvent.click(screen.getByLabelText(ru['steps.play']));
    await waitFor(() =>
      expect(track.style.getPropertyValue('--time-scale-glide')).not.toBe('0ms')
    );
  });

  it('ignores clicks in the empty space above the rail', async () => {
    const { container } = renderConsole();
    await screen.findByTestId('time-scale');
    seekTo(container, 5);
    await waitFor(() => expect(stepPosition(container)).toContain('6'));
    const track = screen.getByTestId('time-scale-track');
    fireEvent.click(track, { clientX: 900 });
    await waitFor(() => expect(stepPosition(container)).toContain('6'));
  });

  it('keeps the range input above the rail so the pointer reaches it', async () => {
    const { container } = renderConsole();
    await screen.findByTestId('time-scale');
    const track = container.querySelector('.time-scale-track') as HTMLElement;
    const children = [...track.children].map((node) => node.className);
    expect(children.indexOf('time-scale-input')).toBeLessThan(
      children.indexOf('time-scale-rail')
    );
  });

  it('places the transport above the scale track', async () => {
    const { container } = renderConsole();
    await screen.findByTestId('time-scale');
    const player = container.querySelector('.time-scale-player') as HTMLElement;
    const track = container.querySelector('.time-scale-track') as HTMLElement;
    expect(player).toBeTruthy();
    expect(track).toBeTruthy();
    const relation = player.compareDocumentPosition(track);
    expect(relation & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  });

  it('jumps to the first and the last step with Home and End', async () => {
    const { container } = renderConsole();
    await screen.findByTestId('time-scale');
    fireEvent.keyDown(window, { key: 'End' });
    await waitFor(() => expect(stepPosition(container)).toContain(String(STEP_COUNT)));
    fireEvent.keyDown(window, { key: 'Home' });
    await waitFor(() => expect(stepPosition(container)).toContain('1'));
  });
});

describe('module wiring', () => {
  it('mounts the command palette without a circular-import crash', async () => {
    const { container } = renderConsole();
    await screen.findByTestId('time-scale');
    fireEvent.keyDown(window, { key: 'k', ctrlKey: true });
    expect(await screen.findByTestId('command-palette')).toBeTruthy();
    expect(container.querySelector('.view-status[data-kind="error"]')).toBeNull();
  });
});

describe('field strip scope', () => {
  it('shows the strip on field and history, hides it on decisions and money', async () => {
    renderConsole();
    await screen.findByTestId('time-scale');
    await screen.findByTestId('console-strip');

    fireEvent.click(navButton(ru['workspace.history']));
    await screen.findByLabelText(ru['chrono.ariaLabel']);
    expect(screen.queryByTestId('console-strip')).toBeTruthy();

    fireEvent.click(navButton(ru['workspace.money']));
    await screen.findByTestId('money-workspace', {}, { timeout: 5000 });
    expect(screen.queryByTestId('console-strip')).toBeNull();

    fireEvent.click(navButton(ru['workspace.decisions']));
    await waitFor(() => expect(screen.queryByTestId('console-strip')).toBeNull());
  });
});

describe('time scale marks', () => {
  it('draws a year tick per year found in the step dates', async () => {
    const { container } = renderConsole();
    await screen.findByTestId('time-scale-track');
    const years = [...container.querySelectorAll('.time-scale-year')].map(
      (node) => node.textContent
    );
    expect(years).toEqual(['2007', '2008']);
  });

  it('marks the terminal step explicitly once it is reached', async () => {
    renderConsole();
    await screen.findByTestId('time-scale');
    expect(screen.queryByText(ru['steps.terminalShort'])).toBeNull();
    fireEvent.keyDown(window, { key: 'End' });
    await waitFor(() =>
      expect(screen.queryByText(ru['steps.terminalShort'])).toBeTruthy()
    );
  });

  it('draws no event marks when the bundle carries no field events', async () => {
    const { container } = renderConsole();
    await screen.findByTestId('time-scale-events');
    expect(container.querySelectorAll('.time-scale-event')).toHaveLength(0);
  });
});

describe('scene highlight', () => {
  it('rings the group and the lambda neighbours of the selected well on the projection', async () => {
    const { container } = renderConsole();
    await screen.findByTestId('field-projection-plot');
    fireEvent.click(await screen.findByLabelText('I1'));

    await waitFor(() =>
      expect(
        container.querySelector('[data-well-id="I1"][data-highlight="selected"]')
      ).not.toBeNull()
    );
    expect(
      container.querySelector('[data-well-id="P1"]')?.getAttribute('data-highlight')
    ).toBe('neighbour');
    expect(
      container
        .querySelector('[data-well-id="P1"]')
        ?.querySelector('[data-neighbour-ring="neighbour"]')
    ).not.toBeNull();
    expect(
      container
        .querySelector('[data-well-id="I1"]')
        ?.querySelector('[data-group-ring="strong"]')
    ).not.toBeNull();
  });
});

describe('money workspace', () => {
  it('switches sub-tabs and each renders only its own content', async () => {
    renderConsole();
    fireEvent.click(navButton(ru['workspace.money']));
    await screen.findByTestId('money-workspace', {}, { timeout: 5000 });
    expect(screen.getByText(ru['npv.title'])).toBeTruthy();
    expect(screen.queryByText(ru['scenarios.library.title'])).toBeNull();
    expect(screen.queryByText(ru['scenarios.editor.title'])).toBeNull();

    fireEvent.click(navButton(ru['view.comparison']));
    await screen.findByText(ru['scenarios.library.title']);
    expect(screen.queryByText(ru['npv.title'])).toBeNull();
    expect(screen.queryByText(ru['scenarios.editor.title'])).toBeNull();

    fireEvent.click(navButton(ru['view.constraints']));
    await screen.findByText(ru['scenarios.editor.title']);
    expect(screen.queryByText(ru['npv.title'])).toBeNull();
    expect(screen.queryByText(ru['scenarios.library.title'])).toBeNull();
  });
});
