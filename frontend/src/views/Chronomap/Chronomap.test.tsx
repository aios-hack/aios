import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { ReactNode } from 'react';
import type { GraphFile, NpvFile, TimelineFile, TimelineStep } from '../../api/types';
import { HistoryViewProvider } from '../../app/HistoryViewContext';
import { dictionaries } from '../../i18n/dictionaries';
import { I18nProvider } from '../../i18n/I18nContext';
import { TimelineProvider, useTimeline } from '../../state/TimelineContext';
import { ThemeProvider } from '../../theme/ThemeContext';
import { mixColors, parseColor, toCanvasColor } from '../shared/canvasColors';
import { Chronomap } from './Chronomap';
import {
  PALETTE_TOKENS,
  cellRgb,
  modeOf,
  readChronoPalette,
  type Palette
} from './cells';
import { CELL_HEIGHT, CELL_WIDTH, CELL_WIDTH_MAX, GUTTER_LEFT, GUTTER_TOP, ROW_GAP, cellWidthFor, geometryOf, hitTest, yearTicks } from './geometry';

const CELL_FILL_HEIGHT = CELL_HEIGHT - ROW_GAP;
import { buildRows, sortRows, ungroupedCount } from './sortRows';
import { paintChronomap } from './useChronomapCanvas';

const { ru } = dictionaries;

const WELL_COUNT = 7;
const STEP_COUNT = 5;

const wellIds = Array.from({ length: WELL_COUNT }, (_, i) => `W${WELL_COUNT - i}`);

const makeStep = (k: number, last: boolean): TimelineStep => ({
  control_step: k,
  date: `${2007 + k}-0${(k % 9) + 1}-01`,
  terminal: last,
  field: {
    production: 2000 + k,
    injection: 1500 + k,
    compensation: 0.75,
    npv_cumulative: 1000 * (k + 1),
    active_wells: WELL_COUNT
  },
  wells: wellIds.map((well, i) => ({
    well,
    availability: i === WELL_COUNT - 1 ? 'NOT_COMMISSIONED' : 'AVAILABLE',
    role: i % 3 === 0 ? 'INJ' : 'PROD',
    operating_status: i === 1 && k > 0 ? 'SHUT' : 'OPEN',
    setpoint: 100,
    liquid_rate: 40 + 10 * k,
    injection_rate: 120,
    bhp: 91,
    watercut: i === 2 ? null : Math.min(0.05 * (i + k), 1),
    fact_to_target: 0.4 + 0.1 * k,
    cumulative_liquid: 1000 * (k + 1)
  }))
});

const timelineFixture: TimelineFile = {
  model: 'Model_Z',
  t0: '2007-01-01',
  n_control_dates: STEP_COUNT,
  n_intervals: STEP_COUNT - 1,
  wells: wellIds,
  steps: Array.from({ length: STEP_COUNT }, (_, k) => makeStep(k, k === STEP_COUNT - 1))
};

const npvFixture: NpvFile = {
  wells: wellIds.map((well, i) => ({
    well,
    pre_tax: 1000 - 100 * i,
    with_allocated_tax: i === 3 ? -400 : 900 - 100 * i
  })),
  total: { pre_tax: 4000, with_allocated_tax: 3000 },
  npv_methodology: 3000
};

const graphFixture: GraphFile = {
  window: { start: '2007-01-01', end: '2009-01-01' },
  nodes: wellIds.map((id, i) => ({
    id,
    role: i % 3 === 0 ? 'INJ' : 'PROD',
    group: null,
    x: i,
    y: i
  })),
  edges: [],
  groups: [
    { id: 'B', wells: wellIds.slice(0, 2) },
    { id: 'A', wells: wellIds.slice(2, 5) }
  ],
  weight_range: { min: 0, max: 1 },
  meta: { lag_months: 2, amplitude: 1, stability: 0.99, rank: 4, condition_number: 3 },
  layout: { size: 100, seed: 1 }
};

interface Spy {
  fillRect: ReturnType<typeof vi.fn>;
  clearRect: ReturnType<typeof vi.fn>;
  fillText: ReturnType<typeof vi.fn>;
  setTransform: ReturnType<typeof vi.fn>;
  fills: string[];
}

const spies: Spy[] = [];

const stubContext = (): CanvasRenderingContext2D => {
  const spy: Spy = {
    fillRect: vi.fn(),
    clearRect: vi.fn(),
    fillText: vi.fn(),
    setTransform: vi.fn(),
    fills: []
  };
  spies.push(spy);
  const ctx = {
    ...spy,
    globalAlpha: 1,
    font: '',
    textAlign: 'left',
    textBaseline: 'top',
    strokeStyle: '',
    beginPath: vi.fn(),
    stroke: vi.fn(),
    fill: vi.fn(),
    arc: vi.fn()
  };
  Object.defineProperty(ctx, 'fillStyle', {
    get: () => spy.fills.at(-1) ?? '',
    set: (value: string) => {
      spy.fills.push(value);
    }
  });
  return ctx as unknown as CanvasRenderingContext2D;
};

const distinctPalette = (): Palette =>
  Object.fromEntries(
    PALETTE_TOKENS.map((token, i) => [
      token,
      { r: 10 + i * 20, g: 200 - i * 15, b: 5 + i * 9, a: 1 }
    ])
  ) as Palette;

const realComputedStyle = window.getComputedStyle.bind(window);

const stubComputedStyle = (values: Record<string, string>) => {
  const patched = ((element: Element, pseudo?: string | null) => {
    const style = realComputedStyle(element, pseudo ?? undefined);
    if (element !== document.documentElement) {
      return style;
    }
    return new Proxy(style, {
      get: (target, key) =>
        key === 'getPropertyValue'
          ? (name: string) => values[name] ?? ''
          : Reflect.get(target, key)
    });
  }) as typeof window.getComputedStyle;
  vi.spyOn(window, 'getComputedStyle').mockImplementation(patched);
};

const Reporter = () => {
  const { stepIndex, selectedWell } = useTimeline();
  return <output data-testid="state">{`${selectedWell ?? '-'}:${stepIndex}`}</output>;
};

const withProviders = (node: ReactNode) => (
  <I18nProvider>
    <ThemeProvider>
      <TimelineProvider>
        <HistoryViewProvider>
          {node}
          <Reporter />
        </HistoryViewProvider>
      </TimelineProvider>
    </ThemeProvider>
  </I18nProvider>
);

const mockRoutes = (timeline: TimelineFile = timelineFixture) => {
  vi.stubGlobal(
    'fetch',
    vi.fn().mockImplementation((url: string) => {
      const payload = url.includes('timeline')
        ? timeline
        : url.includes('npv')
          ? npvFixture
          : graphFixture;
      return Promise.resolve({ ok: true, json: () => Promise.resolve(payload) });
    })
  );
};

const cellCalls = (): unknown[][] =>
  spies.flatMap((spy) =>
    spy.fillRect.mock.calls.filter(
      (call) => call[2] === CELL_WIDTH && call[3] === CELL_FILL_HEIGHT
    )
  );

const paintPasses = (): number => cellCalls().length / (STEP_COUNT * WELL_COUNT);

const rowLabels = (): string[] =>
  spies.flatMap((spy) =>
    spy.fillText.mock.calls
      .map((call) => String(call[0]))
      .filter((text) => text.startsWith('W'))
  );

const labelsPerPass = (): number => rowLabels().length / paintPasses();

const lastLabelPass = (): string[] => rowLabels().slice(-labelsPerPass());

const matrixCanvas = (container: HTMLElement): HTMLCanvasElement => {
  const canvas = container.querySelector<HTMLCanvasElement>('.chronomap-canvas');
  if (canvas === null) {
    throw new Error('no matrix canvas');
  }
  return canvas;
};

const clickCell = (canvas: HTMLCanvasElement, column: number, row: number) => {
  const event = new MouseEvent('click', { bubbles: true });
  Object.defineProperty(event, 'offsetX', {
    value: GUTTER_LEFT + column * CELL_WIDTH + 1
  });
  Object.defineProperty(event, 'offsetY', { value: GUTTER_TOP + row * CELL_HEIGHT + 1 });
  fireEvent(canvas, event);
};

const hoverCell = (canvas: HTMLCanvasElement, column: number, row: number) => {
  const event = new MouseEvent('mousemove', { bubbles: true });
  Object.defineProperty(event, 'offsetX', {
    value: GUTTER_LEFT + column * CELL_WIDTH + 1
  });
  Object.defineProperty(event, 'offsetY', { value: GUTTER_TOP + row * CELL_HEIGHT + 1 });
  fireEvent(canvas, event);
};

beforeEach(() => {
  localStorage.clear();
  spies.length = 0;
  HTMLCanvasElement.prototype.getContext = vi.fn(
    stubContext
  ) as unknown as HTMLCanvasElement['getContext'];
});

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

const HASH = String.fromCharCode(35);
const hex = (digits: string): string => `${HASH}${digits}`;

describe('canvas colour resolution', () => {
  it('parses hex, short hex and rgba into channels canvas understands', () => {
    expect(parseColor(hex('0e1116'))).toEqual({ r: 14, g: 17, b: 22, a: 1 });
    expect(parseColor(` ${hex('abc')} `)).toEqual({ r: 170, g: 187, b: 204, a: 1 });
    expect(parseColor('rgba(221, 227, 234, 0.32)')).toEqual({
      r: 221,
      g: 227,
      b: 234,
      a: 0.32
    });
    expect(parseColor('rgb(1 2 3)')).toEqual({ r: 1, g: 2, b: 3, a: 1 });
    expect(parseColor('color-mix(in oklab, red, blue)')).toBeNull();
    expect(parseColor('')).toBeNull();
  });

  it('interpolates between two resolved colours and emits an rgb string', () => {
    const from = { r: 0, g: 0, b: 0, a: 1 };
    const to = { r: 100, g: 200, b: 50, a: 1 };
    expect(mixColors(from, to, 0.5)).toEqual({ r: 50, g: 100, b: 25, a: 1 });
    expect(mixColors(from, to, -1)).toEqual(from);
    expect(mixColors(from, to, 2)).toEqual(to);
    expect(toCanvasColor(mixColors(from, to, 0.5))).toBe('rgb(50, 100, 25)');
    expect(toCanvasColor({ r: 1, g: 2, b: 3, a: 0.5 })).toBe('rgba(1, 2, 3, 0.500)');
  });

  it('reads the palette out of the css variables the theme defines', () => {
    stubComputedStyle({
      '--scale-watercut-0': hex('d9973f'),
      '--scale-watercut-1': hex('4fb3c9'),
      '--color-unknown': 'rgba(221, 227, 234, 0.32)'
    });
    const palette = readChronoPalette(document.documentElement);
    expect(palette['--scale-watercut-0']).toEqual({ r: 217, g: 151, b: 63, a: 1 });
    expect(palette['--scale-watercut-1']).toEqual({ r: 79, g: 179, b: 201, a: 1 });
    expect(palette['--color-unknown'].a).toBeCloseTo(0.32);
  });

  it('never hands canvas a colour it cannot parse, even with no variables set', () => {
    stubComputedStyle({});
    const palette = readChronoPalette(document.documentElement);
    for (const value of Object.values(palette)) {
      expect(toCanvasColor(value)).toMatch(/^rgba?\(/);
    }
  });
});

describe('chronomap geometry', () => {
  it('derives canvas size from the data lengths, not from constants', () => {
    const small = geometryOf(STEP_COUNT, WELL_COUNT);
    const large = geometryOf(STEP_COUNT * 3, WELL_COUNT * 2);
    expect(small.plotWidth).toBe(STEP_COUNT * CELL_WIDTH);
    expect(small.plotHeight).toBe(WELL_COUNT * CELL_HEIGHT);
    expect(large.width - GUTTER_LEFT).toBe(small.plotWidth * 3);
    expect(large.height - GUTTER_TOP).toBe(small.plotHeight * 2);
  });

  it('maps pointer offsets back to a cell and rejects the gutters', () => {
    const geometry = geometryOf(STEP_COUNT, WELL_COUNT);
    expect(hitTest(GUTTER_LEFT + CELL_WIDTH * 2 + 1, GUTTER_TOP + CELL_HEIGHT * 3 + 1, geometry)).toEqual({
      column: 2,
      row: 3
    });
    expect(hitTest(GUTTER_LEFT - 1, GUTTER_TOP + 1, geometry)).toBeNull();
    expect(hitTest(GUTTER_LEFT + 1, GUTTER_TOP - 1, geometry)).toBeNull();
    expect(
      hitTest(GUTTER_LEFT + CELL_WIDTH * STEP_COUNT + 1, GUTTER_TOP + 1, geometry)
    ).toBeNull();
  });

  it('widens the cells to spend the room the container offers, up to the ceiling', () => {
    expect(cellWidthFor(100, GUTTER_LEFT + 800)).toBe(8);
    expect(cellWidthFor(100, GUTTER_LEFT + 100000)).toBe(CELL_WIDTH_MAX);
  });

  it('never shrinks a cell below the readable minimum when the container is cramped', () => {
    expect(cellWidthFor(1000, GUTTER_LEFT + 100)).toBe(CELL_WIDTH);
    expect(cellWidthFor(100, 0)).toBe(CELL_WIDTH);
    expect(cellWidthFor(0, 2000)).toBe(CELL_WIDTH);
    expect(cellWidthFor(100, Number.NaN)).toBe(CELL_WIDTH);
  });

  it('maps a pointer offset through the widened cell width, not the default one', () => {
    const wide = geometryOf(STEP_COUNT, WELL_COUNT, 10);
    expect(wide.width - GUTTER_LEFT).toBe(STEP_COUNT * 10);
    expect(hitTest(GUTTER_LEFT + 25, GUTTER_TOP + 1, wide)).toEqual({ column: 2, row: 0 });
    expect(hitTest(GUTTER_LEFT + STEP_COUNT * 10 + 1, GUTTER_TOP + 1, wide)).toBeNull();
  });

  it('marks the first step of every year from the dates in the data', () => {
    const ticks = yearTicks(timelineFixture.steps.map((step) => step.date));
    expect(ticks).toHaveLength(STEP_COUNT);
    expect(ticks[0]).toEqual({ column: 0, year: '2007' });
    expect(yearTicks(['2007-01-01', '2007-02-01', '2008-01-01'])).toEqual([
      { column: 0, year: '2007' },
      { column: 2, year: '2008' }
    ]);
  });
});

describe('chronomap row order', () => {
  const npv = new Map(npvFixture.wells.map((row) => [row.well, row.with_allocated_tax]));
  const groups = new Map<string, string>();
  for (const group of graphFixture.groups) {
    for (const well of group.wells) {
      groups.set(well, group.id);
    }
  }
  const rows = buildRows(wellIds, groups, npv);

  it('sorts by well number, not by the order in the file', () => {
    expect(sortRows(rows, 'well').map((row) => row.well)).toEqual([
      'W1',
      'W2',
      'W3',
      'W4',
      'W5',
      'W6',
      'W7'
    ]);
  });

  it('puts wells outside every area at the end instead of dropping them', () => {
    const ordered = sortRows(rows, 'group');
    expect(ordered.slice(-2).every((row) => row.group === null)).toBe(true);
    expect(ordered[0].group).toBe('A');
    expect(ungroupedCount(ordered)).toBe(2);
    expect(ordered).toHaveLength(WELL_COUNT);
  });

  it('sorts by npv contribution descending and keeps the loss-making well last', () => {
    const ordered = sortRows(rows, 'npv').map((row) => row.well);
    expect(ordered[0]).toBe('W7');
    expect(ordered.at(-1)).toBe('W4');
  });
});

describe('chronomap cell colours', () => {
  const palette = distinctPalette();
  const context = { metric: 'watercut' as const, palette, npv: new Map(), npvCeiling: 0 };
  const row = timelineFixture.steps[0].wells[1];

  it('classifies mode from availability and status, not from role alone', () => {
    expect(modeOf(timelineFixture.steps[1].wells[1])).toBe('shut');
    expect(modeOf(timelineFixture.steps[0].wells[0])).toBe('injection');
    expect(modeOf(timelineFixture.steps[0].wells[1])).toBe('production');
    expect(modeOf(timelineFixture.steps[0].wells[WELL_COUNT - 1])).toBe('idle');
  });

  it('separates a missing watercut from a measured one', () => {
    const missing = cellRgb(timelineFixture.steps[0].wells[2], context);
    const measured = cellRgb(row, context);
    expect(toCanvasColor(missing)).not.toBe(toCanvasColor(measured));
    expect(toCanvasColor(missing)).toBe(toCanvasColor(palette['--color-unknown']));
  });

  it('keeps a not commissioned well visible against the canvas background', () => {
    const opaque: Palette = {
      ...palette,
      '--color-plot-bg': { r: 236, g: 239, b: 243, a: 1 },
      '--color-well-dim': { r: 26, g: 32, b: 40, a: 0.2 }
    };
    const idle = timelineFixture.steps[0].wells[WELL_COUNT - 1];
    const painted = toCanvasColor(cellRgb(idle, { ...context, palette: opaque }));
    expect(painted).not.toBe(toCanvasColor(opaque['--color-plot-bg']));
    expect(painted).toBe('rgb(194, 198, 202)');
  });

  it('changes the cell colour when the metric changes', () => {
    const watercut = toCanvasColor(cellRgb(row, context));
    const ratio = toCanvasColor(cellRgb(row, { ...context, metric: 'ratio' }));
    const mode = toCanvasColor(cellRgb(row, { ...context, metric: 'mode' }));
    expect(new Set([watercut, ratio, mode]).size).toBe(3);
  });
});

describe('Chronomap view', () => {
  it('sizes the canvas from the data lengths and marks it with them', async () => {
    mockRoutes();
    const { container } = render(withProviders(<Chronomap />));
    await waitFor(() => expect(container.querySelector('.chronomap-canvas')).not.toBeNull());
    const canvas = matrixCanvas(container);
    await waitFor(() => expect(canvas.width).toBeGreaterThan(0));
    const geometry = geometryOf(STEP_COUNT, WELL_COUNT);
    expect(canvas.dataset.columns).toBe(String(STEP_COUNT));
    expect(canvas.dataset.rows).toBe(String(WELL_COUNT));
    expect(canvas.style.width).toBe(`${geometry.width}px`);
    expect(canvas.style.height).toBe(`${geometry.height}px`);
  });

  it('grows the canvas when the data carries more steps and wells', async () => {
    const wide: TimelineFile = {
      ...timelineFixture,
      steps: [...timelineFixture.steps, makeStep(STEP_COUNT, true)]
    };
    mockRoutes(wide);
    const { container } = render(withProviders(<Chronomap />));
    await waitFor(() => expect(container.querySelector('.chronomap-canvas')).not.toBeNull());
    const canvas = matrixCanvas(container);
    await waitFor(() => expect(canvas.dataset.columns).toBe(String(STEP_COUNT + 1)));
    expect(canvas.style.width).toBe(`${geometryOf(STEP_COUNT + 1, WELL_COUNT).width}px`);
  });

  it('fills one rectangle per cell of the matrix', async () => {
    mockRoutes();
    const { container } = render(withProviders(<Chronomap />));
    await waitFor(() => expect(container.querySelector('.chronomap-canvas')).not.toBeNull());
    await waitFor(() =>
      expect(matrixCanvas(container).dataset.rows).toBe(String(WELL_COUNT))
    );
    await waitFor(() => expect(cellCalls().length).toBeGreaterThan(0));
    expect(cellCalls().length % (STEP_COUNT * WELL_COUNT)).toBe(0);
    expect(cellCalls()[0]).toEqual([GUTTER_LEFT, GUTTER_TOP, CELL_WIDTH, CELL_FILL_HEIGHT]);
  });

  it('selects the well and the step when a cell is clicked', async () => {
    mockRoutes();
    const { container } = render(withProviders(<Chronomap />));
    await waitFor(() => expect(container.querySelector('.chronomap-canvas')).not.toBeNull());
    const canvas = matrixCanvas(container);
    await waitFor(() => expect(canvas.dataset.rows).toBe(String(WELL_COUNT)));

    clickCell(canvas, 3, 2);

    expect(screen.getByTestId('state').textContent).toBe('W3:3');
  });

  it('walks the matrix with the arrows and selects on Enter (R15)', async () => {
    mockRoutes();
    const { container } = render(withProviders(<Chronomap />));
    await waitFor(() => expect(container.querySelector('.chronomap-canvas')).not.toBeNull());
    const canvas = matrixCanvas(container);
    await waitFor(() => expect(canvas.dataset.rows).toBe(String(WELL_COUNT)));

    expect(canvas.getAttribute('tabindex')).toBe('0');
    fireEvent.keyDown(canvas, { key: 'ArrowDown' });
    fireEvent.keyDown(canvas, { key: 'ArrowRight' });
    fireEvent.keyDown(canvas, { key: 'Enter' });

    expect(screen.getByTestId('state').textContent).toBe('W2:1');
  });

  it('announces the focused cell for screen readers (R15)', async () => {
    mockRoutes();
    const { container } = render(withProviders(<Chronomap />));
    await waitFor(() => expect(container.querySelector('.chronomap-canvas')).not.toBeNull());
    const canvas = matrixCanvas(container);
    await waitFor(() => expect(canvas.dataset.rows).toBe(String(WELL_COUNT)));

    const announce = screen.getByTestId('chronomap-announce');
    expect(announce.getAttribute('aria-live')).toBe('polite');
    fireEvent.keyDown(canvas, { key: 'ArrowDown' });
    await waitFor(() => expect(announce.textContent?.length ?? 0).toBeGreaterThan(0));
  });

  it('keeps clicks in the gutter from changing the selection', async () => {
    mockRoutes();
    const { container } = render(withProviders(<Chronomap />));
    await waitFor(() => expect(container.querySelector('.chronomap-canvas')).not.toBeNull());
    const canvas = matrixCanvas(container);
    await waitFor(() => expect(canvas.dataset.rows).toBe(String(WELL_COUNT)));

    const event = new MouseEvent('click', { bubbles: true });
    Object.defineProperty(event, 'offsetX', { value: 2 });
    Object.defineProperty(event, 'offsetY', { value: 2 });
    fireEvent(canvas, event);

    expect(screen.getByTestId('state').textContent).toBe('-:0');
  });

  it('shows the well, the date and the value on hover', async () => {
    mockRoutes();
    const { container } = render(withProviders(<Chronomap />));
    await waitFor(() => expect(container.querySelector('.chronomap-canvas')).not.toBeNull());
    const canvas = matrixCanvas(container);
    await waitFor(() => expect(canvas.dataset.rows).toBe(String(WELL_COUNT)));

    hoverCell(canvas, 1, 0);

    const tip = await screen.findByRole('tooltip');
    expect(tip.textContent).toContain('W1');
    expect(tip.textContent).toContain('2008');
    expect(tip.textContent).not.toContain(ru['chrono.terminalNote']);
  });

  it('names the terminal step as a state without an interval', async () => {
    mockRoutes();
    const { container } = render(withProviders(<Chronomap />));
    await waitFor(() => expect(container.querySelector('.chronomap-canvas')).not.toBeNull());
    const canvas = matrixCanvas(container);
    await waitFor(() => expect(canvas.dataset.rows).toBe(String(WELL_COUNT)));

    hoverCell(canvas, STEP_COUNT - 1, 0);

    const tip = await screen.findByRole('tooltip');
    expect(tip.textContent).toContain(ru['chrono.terminalNote']);
  });

  it('keeps the step cursor on its own canvas so the matrix is not repainted', async () => {
    mockRoutes();
    const { container } = render(withProviders(<Chronomap />));
    await waitFor(() => expect(container.querySelector('.chronomap-cursor')).not.toBeNull());
    const canvas = matrixCanvas(container);
    await waitFor(() => expect(canvas.dataset.rows).toBe(String(WELL_COUNT)));
    const painted = cellCalls().length;

    clickCell(canvas, 4, 1);

    const cursor = container.querySelector<HTMLCanvasElement>('.chronomap-cursor');
    await waitFor(() => expect(cursor?.dataset.step).toBe('4'));
    expect(cellCalls().length).toBe(painted);
  });

  it('repaints every cell of the matrix when the metric changes', async () => {
    mockRoutes();
    const { container } = render(withProviders(<Chronomap />));
    await waitFor(() => expect(container.querySelector('.chronomap-canvas')).not.toBeNull());
    await waitFor(() => expect(matrixCanvas(container).dataset.rows).toBe(String(WELL_COUNT)));
    await waitFor(() => expect(cellCalls().length).toBeGreaterThan(0));
    const passes = paintPasses();

    fireEvent.click(screen.getByText(ru['history.metric.mode']));

    await waitFor(() => expect(paintPasses()).toBe(passes + 1));
  });

  it('reorders the row labels when the sort changes without losing a row', async () => {
    mockRoutes();
    const { container } = render(withProviders(<Chronomap />));
    await waitFor(() => expect(container.querySelector('.chronomap-canvas')).not.toBeNull());
    await waitFor(() => expect(matrixCanvas(container).dataset.rows).toBe(String(WELL_COUNT)));
    await waitFor(() => expect(rowLabels().length).toBeGreaterThan(0));
    const passes = paintPasses();
    const before = lastLabelPass();

    fireEvent.click(screen.getByText(ru['history.sort.npv']));

    await waitFor(() => expect(paintPasses()).toBe(passes + 1));
    const after = lastLabelPass();
    expect(after).toHaveLength(before.length);
    expect(after).not.toEqual(before);
    expect(new Set(after).size).toBe(after.length);
    expect(cellCalls().length % (STEP_COUNT * WELL_COUNT)).toBe(0);
  });

  it('reports how many wells fall outside every area', async () => {
    mockRoutes();
    render(withProviders(<Chronomap />));
    await waitFor(() => expect(document.querySelector('.chronomap-canvas')).not.toBeNull());
    fireEvent.click(screen.getByLabelText(ru['toolbar.legend']));
    await screen.findByText(ru['chrono.ungrouped'].replace('{count}', '2'));
  });

  it('repaints the matrix with the new palette when the theme changes', async () => {
    mockRoutes();
    const { container } = render(withProviders(<Chronomap />));
    await waitFor(() => expect(container.querySelector('.chronomap-canvas')).not.toBeNull());
    await waitFor(() => expect(matrixCanvas(container).dataset.rows).toBe(String(WELL_COUNT)));
    await waitFor(() => expect(cellCalls().length).toBeGreaterThan(0));
    const passes = paintPasses();

    stubComputedStyle(
      Object.fromEntries(PALETTE_TOKENS.map((token) => [token, hex('112233')]))
    );
    document.documentElement.dataset.theme =
      document.documentElement.dataset.theme === 'dark' ? 'light' : 'dark';

    await waitFor(() => expect(paintPasses()).toBeGreaterThan(passes));
    expect(spies.flatMap((spy) => spy.fills)).toContain('rgb(17, 34, 51)');
  });

  it('shows a russian error message when the timeline cannot be loaded', async () => {
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new Error('network')));
    render(withProviders(<Chronomap />));
    await screen.findByText(ru['chrono.error']);
  });

  it('tells the user the roster is empty instead of drawing a bare matrix', async () => {
    mockRoutes({ ...timelineFixture, wells: [] });
    render(withProviders(<Chronomap />));
    await screen.findByText(ru['chrono.empty']);
    expect(screen.getByText(ru['chrono.emptyHint'])).toBeTruthy();
  });

  it('keeps the toolbar at or under the seven-control budget (R5)', async () => {
    mockRoutes();
    const { container } = render(withProviders(<Chronomap />));
    await waitFor(() => expect(container.querySelector('.chronomap-canvas')).not.toBeNull());
    const toolbar = container.querySelector('.view-toolbar');
    expect(toolbar).not.toBeNull();
    const controls = toolbar!.querySelectorAll(
      ':scope > .view-toolbar-group > [role="group"], :scope > .view-toolbar-group > .popover-wrap, :scope > .view-toolbar-group > select, :scope > .view-toolbar-group > input'
    );
    expect(controls.length).toBeLessThanOrEqual(7);
  });

  it('measures the matrix inside a frame so the cells can spend the room available', async () => {
    mockRoutes();
    const { container } = render(withProviders(<Chronomap />));
    await waitFor(() => expect(container.querySelector('.chronomap-canvas')).not.toBeNull());
    const frame = container.querySelector<HTMLElement>('.chronomap-frame');
    const stage = container.querySelector<HTMLElement>('.chronomap-stage');
    expect(frame).not.toBeNull();
    expect(frame!.contains(stage!)).toBe(true);
    expect(frame!.parentElement?.classList.contains('chronomap-body')).toBe(true);
    const width = Number(stage!.style.width.replace('px', ''));
    expect(width).toBe(GUTTER_LEFT + STEP_COUNT * cellWidthFor(STEP_COUNT, frame!.clientWidth));
  });

  it('renders ui/Legend inside the legend popover', async () => {
    mockRoutes();
    render(withProviders(<Chronomap />));
    await waitFor(() => expect(document.querySelector('.chronomap-canvas')).not.toBeNull());
    fireEvent.click(screen.getByLabelText(ru['toolbar.legend']));
    expect(screen.getByRole('group', { name: ru['chrono.legend.title'] })).toBeTruthy();
    expect(screen.getByTestId('chrono-legend-size')).toBeTruthy();
  });
});

const countingContext = (
  cellWidth: number = CELL_WIDTH
): { ctx: CanvasRenderingContext2D; cells: () => number } => {
  let cells = 0;
  const noop = () => {};
  const ctx = {
    fillRect: (_x: number, _y: number, w: number, h: number) => {
      if (w === cellWidth && h === CELL_FILL_HEIGHT) {
        cells += 1;
      }
    },
    clearRect: noop,
    fillText: noop,
    setTransform: noop,
    beginPath: noop,
    stroke: noop,
    fill: noop,
    arc: noop,
    globalAlpha: 1,
    fillStyle: '',
    strokeStyle: '',
    font: '',
    textAlign: 'left',
    textBaseline: 'top'
  };
  return { ctx: ctx as unknown as CanvasRenderingContext2D, cells: () => cells };
};

describe('chronomap paint budget', () => {

  const fullSizedPaint = (columns: number, rows: number) => {
    const wells = Array.from({ length: rows }, (_, i) => `P${i + 1}`);
    const template = timelineFixture.steps[0].wells[1];
    const steps: TimelineStep[] = Array.from({ length: columns }, (_, k) => ({
      ...timelineFixture.steps[0],
      control_step: k,
      terminal: k === columns - 1,
      date: `${2007 + Math.floor(k / 12)}-01-01`
    }));
    const index = steps.map(
      () => new Map(wells.map((well) => [well, { ...template, well }]))
    );
    return {
      geometry: geometryOf(columns, rows),
      rows: wells.map((well) => ({ well, group: null, npv: undefined, watercut: undefined })),
      steps,
      index,
      context: {
        metric: 'watercut' as const,
        palette: distinctPalette(),
        npv: new Map<string, number>(),
        npvCeiling: 0
      },
      axisColor: 'rgb(0, 0, 0)',
      surfaceColor: 'rgb(1, 1, 1)'
    };
  };

  it('paints every cell at the widened width when the container gave the room', () => {
    const columns = 20;
    const rows = wellIds.length;
    const base = fullSizedPaint(columns, rows);
    const paint = { ...base, geometry: geometryOf(columns, rows, 9) };

    const wide = countingContext(9);
    paintChronomap(wide.ctx, paint);
    expect(wide.cells()).toBe(columns * rows);

    const narrow = countingContext(CELL_WIDTH);
    paintChronomap(narrow.ctx, paint);
    expect(narrow.cells()).toBe(0);
  });

  it('repaints a matrix of the production size without scanning it more than once', () => {
    const columns = timelineFixture.n_control_dates * 45;
    const rows = wellIds.length * 15;
    const paint = fullSizedPaint(columns, rows);
    const { ctx, cells } = countingContext();
    const metrics = ['watercut', 'mode', 'ratio', 'watercut', 'mode'] as const;

    paintChronomap(ctx, paint);
    const painted = cells();

    const timeOf = (run: () => void): number => {
      const start = performance.now();
      run();
      return performance.now() - start;
    };

    const small = fullSizedPaint(timelineFixture.n_control_dates, wellIds.length);
    const baseline = Math.min(
      ...metrics.map((metric) =>
        timeOf(() => paintChronomap(ctx, { ...small, context: { ...small.context, metric } }))
      )
    );
    const timings = metrics.map((metric) =>
      timeOf(() => paintChronomap(ctx, { ...paint, context: { ...paint.context, metric } }))
    );

    expect(painted).toBe(columns * rows);
    expect(cells()).toBe(columns * rows * (metrics.length + 1) + timelineFixture.n_control_dates * wellIds.length * metrics.length);

    const cellRatio = (columns * rows) / (timelineFixture.n_control_dates * wellIds.length);
    const timeRatio = Math.min(...timings) / Math.max(baseline, 0.01);
    expect(timeRatio).toBeLessThan(cellRatio * 2);
  });
});
