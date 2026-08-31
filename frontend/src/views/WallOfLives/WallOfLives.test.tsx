import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { ReactNode } from 'react';
import type { GraphFile, NpvFile, TimelineFile, TimelineStep } from '../../api/types';
import { HistoryViewProvider } from '../../app/HistoryViewContext';
import { dictionaries } from '../../i18n/dictionaries';
import { I18nProvider } from '../../i18n/I18nContext';
import { TimelineProvider, useTimeline } from '../../state/TimelineContext';
import { ThemeProvider } from '../../theme/ThemeContext';
import { WallOfLives } from './WallOfLives';
import {
  TILE_GAP,
  TILE_HEIGHT,
  TILE_HEIGHT_MAX,
  TILE_WIDTH,
  TILE_WIDTH_MAX,
  layoutOf,
  stepAt,
  stepX,
  tileIndexAt,
  tileX,
  tileY
} from './layout';
import { buildSeries, lastObservedIndex, seriesCeiling, watercutByWell } from './series';
import { buildWallRows, sortWallRows, ungroupedWells } from './wallSort';
import { paintWallCursor } from './useWallCanvas';

const { ru } = dictionaries;

const WELL_COUNT = 6;
const STEP_COUNT = 5;

const wellIds = Array.from({ length: WELL_COUNT }, (_, i) => `W${WELL_COUNT - i}`);

const makeStep = (k: number, last: boolean): TimelineStep => ({
  control_step: k,
  date: `${2007 + k}-01-01`,
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
    operating_status: i === 1 && k > 1 ? 'SHUT' : 'OPEN',
    setpoint: 100,
    liquid_rate: 40 + 10 * k + i,
    injection_rate: 120 + i,
    bhp: 91,
    watercut: i === 2 ? null : Math.min(0.05 * (i + k), 1),
    fact_to_target: 0.5,
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
    { id: 'A', wells: wellIds.slice(2, 4) }
  ],
  weight_range: { min: 0, max: 1 },
  meta: { lag_months: 2, amplitude: 1, stability: 0.99, rank: 4, condition_number: 3 },
  layout: { size: 100, seed: 1 }
};

interface Spy {
  fillRect: ReturnType<typeof vi.fn>;
  clearRect: ReturnType<typeof vi.fn>;
  strokeRect: ReturnType<typeof vi.fn>;
  fillText: ReturnType<typeof vi.fn>;
  moveTo: ReturnType<typeof vi.fn>;
  lineTo: ReturnType<typeof vi.fn>;
  stroke: ReturnType<typeof vi.fn>;
  setTransform: ReturnType<typeof vi.fn>;
  fills: string[];
}

const spies: Spy[] = [];

const stubContext = (): CanvasRenderingContext2D => {
  const spy: Spy = {
    fillRect: vi.fn(),
    clearRect: vi.fn(),
    strokeRect: vi.fn(),
    fillText: vi.fn(),
    moveTo: vi.fn(),
    lineTo: vi.fn(),
    stroke: vi.fn(),
    setTransform: vi.fn(),
    fills: []
  };
  spies.push(spy);
  const ctx = {
    ...spy,
    globalAlpha: 1,
    lineWidth: 1,
    font: '',
    textAlign: 'left',
    textBaseline: 'top',
    strokeStyle: '',
    beginPath: vi.fn(),
    closePath: vi.fn(),
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

const Reporter = () => {
  const { stepIndex, selectedWell, setStepIndex } = useTimeline();
  return (
    <div>
      <output data-testid="state">{`${selectedWell ?? '-'}:${stepIndex}`}</output>
      <button
        type="button"
        data-testid="advance"
        onClick={() => setStepIndex((step) => step + 1)}
      >
        next
      </button>
    </div>
  );
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

const wallCanvas = (): HTMLCanvasElement => {
  const canvas = document.querySelector<HTMLCanvasElement>('.wall-canvas');
  if (canvas === null) {
    throw new Error('no wall canvas');
  }
  return canvas;
};

const wellOrder = (): string[] => (wallCanvas().dataset.wells ?? '').split(' ');

const renderWall = async () => {
  mockRoutes();
  const view = render(withProviders(<WallOfLives />));
  await waitFor(() => expect(document.querySelector('.wall-canvas')).not.toBeNull());
  await waitFor(() => expect(wellOrder().length).toBe(WELL_COUNT));
  return view;
};

const wideWidth = (columns: number): number => (TILE_WIDTH + TILE_GAP) * columns;

const openLegend = () => {
  if (screen.queryByRole('group', { name: ru['wall.legend.title'] }) !== null) {
    return;
  }
  fireEvent.click(screen.getByLabelText(ru['toolbar.legend']));
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

describe('wall layout', () => {
  it('derives the tile count from the data and the columns from the width', () => {
    const wide = layoutOf(WELL_COUNT, wideWidth(3));
    const narrow = layoutOf(WELL_COUNT, TILE_WIDTH);
    expect(wide.count).toBe(WELL_COUNT);
    expect(wide.columns).toBe(3);
    expect(wide.rows).toBe(Math.ceil(WELL_COUNT / 3));
    expect(narrow.columns).toBe(1);
    expect(narrow.rows).toBe(WELL_COUNT);
    expect(narrow.height).toBeGreaterThan(wide.height);
  });

  it('never reports zero columns and keeps an empty wall empty', () => {
    expect(layoutOf(WELL_COUNT, 0).columns).toBe(1);
    const empty = layoutOf(0, wideWidth(3));
    expect(empty.rows).toBe(0);
    expect(empty.height).toBe(0);
  });

  it('maps a pointer onto the tile under it and rejects everything past the last', () => {
    const layout = layoutOf(WELL_COUNT, wideWidth(4));
    expect(tileIndexAt(1, tileY(0, layout) + 1, layout)).toBe(0);
    expect(tileIndexAt(tileX(2, layout) + 1, tileY(2, layout) + 1, layout)).toBe(2);
    expect(tileIndexAt(tileX(5, layout) + 1, tileY(5, layout) + 1, layout)).toBe(5);
    expect(tileIndexAt(-1, 4, layout)).toBeNull();
    expect(tileIndexAt(4, layout.height + layout.cellHeight, layout)).toBeNull();
  });

  it('spreads the steps across the tile width from first to last', () => {
    expect(stepX(0, STEP_COUNT)).toBe(0);
    expect(stepX(STEP_COUNT - 1, STEP_COUNT)).toBe(TILE_WIDTH);
    expect(stepX(0, 1)).toBe(0);
  });
});

describe('wall series', () => {
  it('builds one series per well in the data with a point per step', () => {
    const series = buildSeries(timelineFixture);
    expect(series.size).toBe(timelineFixture.wells.length);
    for (const entry of series.values()) {
      expect(entry.points.length).toBe(timelineFixture.steps.length);
    }
  });

  it('reads the injector rate from injection and marks shut and idle steps', () => {
    const series = buildSeries(timelineFixture);
    const injector = series.get(wellIds[0]);
    const shut = series.get(wellIds[1]);
    const idle = series.get(wellIds[WELL_COUNT - 1]);
    expect(injector?.injector).toBe(true);
    expect(injector?.points[0].rate).toBe(
      timelineFixture.steps[0].wells[0].injection_rate
    );
    expect(shut?.points.filter((point) => point.shut).length).toBeGreaterThan(0);
    expect(idle?.points.every((point) => point.idle)).toBe(true);
    expect(idle?.points.every((point) => point.rate === null)).toBe(true);
  });

  it('takes the water cut from the last observed step, never the terminal one', () => {
    const observed = lastObservedIndex(timelineFixture);
    expect(observed).toBe(STEP_COUNT - 2);
    expect(timelineFixture.steps[observed].terminal).toBe(false);
    const series = buildSeries(timelineFixture);
    const expected = timelineFixture.steps[observed].wells[0].watercut;
    expect(series.get(wellIds[0])?.lastWatercut).toBe(expected);
    expect(watercutByWell(series).has(wellIds[2])).toBe(false);
  });

  it('takes the rate ceiling from the data rather than a constant', () => {
    const ceiling = seriesCeiling(buildSeries(timelineFixture));
    const rates = timelineFixture.steps.flatMap((step) =>
      step.wells
        .filter((row) => row.availability !== 'NOT_COMMISSIONED')
        .map((row) => (row.role === 'INJ' ? row.injection_rate : row.liquid_rate))
    );
    expect(ceiling).toBe(Math.max(...rates));
  });
});

describe('wall sorting', () => {
  const groups = new Map([
    [wellIds[0], 'B'],
    [wellIds[1], 'B'],
    [wellIds[2], 'A'],
    [wellIds[3], 'A']
  ]);
  const npv = new Map(npvFixture.wells.map((row) => [row.well, row.with_allocated_tax]));
  const watercut = watercutByWell(buildSeries(timelineFixture));
  const rows = buildWallRows(wellIds, groups, npv, watercut);

  it('changes the order without changing the set of wells', () => {
    const byWell = sortWallRows(rows, 'well').map((row) => row.well);
    const byNpv = sortWallRows(rows, 'npv').map((row) => row.well);
    const byGroup = sortWallRows(rows, 'group').map((row) => row.well);
    const byWatercut = sortWallRows(rows, 'watercut').map((row) => row.well);
    for (const order of [byNpv, byGroup, byWatercut]) {
      expect(order).not.toEqual(byWell);
      expect([...order].sort()).toEqual([...byWell].sort());
      expect(order.length).toBe(wellIds.length);
    }
  });

  it('orders by number, by npv descending and by water cut descending', () => {
    expect(sortWallRows(rows, 'well').map((row) => row.well)).toEqual(
      [...wellIds].reverse()
    );
    const byNpv = sortWallRows(rows, 'npv');
    expect(byNpv[0].npv).toBe(Math.max(...npv.values()));
    expect(byNpv.at(-1)?.npv).toBe(Math.min(...npv.values()));
    const byWatercut = sortWallRows(rows, 'watercut').map((row) => row.watercut);
    const measured = byWatercut.filter((value): value is number => value !== undefined);
    expect([...measured].sort((a, b) => b - a)).toEqual(measured);
    expect(byWatercut.at(-1)).toBeUndefined();
  });

  it('pushes wells with no area to the end and names them', () => {
    const byGroup = sortWallRows(rows, 'group');
    const ungrouped = ungroupedWells(byGroup);
    expect(ungrouped.length).toBeGreaterThan(0);
    expect(byGroup.slice(-ungrouped.length).every((row) => row.group === null)).toBe(true);
    expect(byGroup.slice(0, -ungrouped.length).every((row) => row.group !== null)).toBe(
      true
    );
  });
});

describe('wall cursor', () => {
  it('draws one mark per tile at the position of the step', () => {
    const layout = layoutOf(WELL_COUNT, wideWidth(3));
    const ctx = stubContext();
    paintWallCursor(ctx, layout, 2, STEP_COUNT, 'rgb(1, 2, 3)');
    const spy = spies.at(-1);
    expect(spy?.fillRect.mock.calls.length).toBe(WELL_COUNT);
    for (const call of spy?.fillRect.mock.calls ?? []) {
      expect(call[2]).toBe(1);
      expect(call[3]).toBe(TILE_HEIGHT);
    }
    expect(spy?.fillRect.mock.calls[0][0]).toBe(
      tileX(0, layout) + stepX(2, STEP_COUNT, layout.tileWidth)
    );
  });

  it('clears and draws nothing when the step is outside the data', () => {
    const layout = layoutOf(WELL_COUNT, wideWidth(3));
    const ctx = stubContext();
    paintWallCursor(ctx, layout, STEP_COUNT, STEP_COUNT, 'rgb(1, 2, 3)');
    const spy = spies.at(-1);
    expect(spy?.clearRect).toHaveBeenCalled();
    expect(spy?.fillRect).not.toHaveBeenCalled();
  });
});

describe('WallOfLives', () => {
  it('hangs the stage inside a frame that measures the row, not inside a bare body', async () => {
    const { container } = await renderWall();
    const frame = container.querySelector<HTMLElement>('.wall-frame');
    const stage = container.querySelector<HTMLElement>('.wall-stage');
    expect(frame).not.toBeNull();
    expect(stage).not.toBeNull();
    expect(frame!.contains(stage!)).toBe(true);
    expect(frame!.parentElement?.classList.contains('wall-body')).toBe(true);
    expect(stage!.querySelector('.wall-canvas')).not.toBeNull();
  });

  it('sizes the stage from the layout so the tiles are not clipped by the frame', async () => {
    const { container } = await renderWall();
    const stage = container.querySelector<HTMLElement>('.wall-stage');
    const layout = layoutOf(WELL_COUNT, wallCanvas().clientWidth);
    expect(stage!.style.width).toBe(`${layout.width}px`);
    expect(stage!.style.height).toBe(`${layout.height}px`);
  });

  it('draws one thumbnail per well in the data', async () => {
    await renderWall();
    expect(wallCanvas().dataset.tiles).toBe(String(timelineFixture.wells.length));
    expect(wellOrder().length).toBe(timelineFixture.wells.length);
    await waitFor(() => {
      const labels = spies.flatMap((spy) =>
        spy.fillText.mock.calls.map((call) => String(call[0]))
      );
      expect(new Set(labels.filter((text) => text.startsWith('W'))).size).toBe(
        timelineFixture.wells.length
      );
    });
  });

  it('changes the order of the thumbnails on a new sort, not their content', async () => {
    await renderWall();
    const before = wellOrder();
    fireEvent.click(screen.getByRole('tab', { name: ru['history.sort.npv'] }));
    await waitFor(() => expect(wellOrder()).not.toEqual(before));
    const after = wellOrder();
    expect([...after].sort()).toEqual([...before].sort());
    expect(wallCanvas().dataset.tiles).toBe(String(before.length));
    expect(wallCanvas().dataset.sort).toBe('npv');
  });

  it('names the wells outside any area when sorting by area', async () => {
    await renderWall();
    fireEvent.click(screen.getByRole('tab', { name: ru['history.sort.group'] }));
    openLegend();
    const note = await screen.findByTestId('wall-ungrouped');
    const grouped = graphFixture.groups.flatMap((group) => group.wells);
    const outside = wellIds.filter((well) => !grouped.includes(well));
    expect(outside.length).toBeGreaterThan(0);
    for (const well of outside) {
      expect(note.textContent).toContain(well);
    }
    expect(wellOrder().slice(-outside.length).sort()).toEqual([...outside].sort());
  });

  it('moves the current step line together with the timeline context', async () => {
    await renderWall();
    expect(
      document.querySelector<HTMLCanvasElement>('.wall-cursor')?.dataset.step
    ).toBe('0');
    const before = spies.flatMap((spy) => spy.fillRect.mock.calls).length;
    fireEvent.click(screen.getByTestId('advance'));
    await waitFor(() => expect(screen.getByTestId('state').textContent).toBe('-:1'));
    await waitFor(() =>
      expect(
        document.querySelector<HTMLCanvasElement>('.wall-cursor')?.dataset.step
      ).toBe('1')
    );
    expect(spies.flatMap((spy) => spy.fillRect.mock.calls).length).toBeGreaterThan(
      before
    );
  });

  it('selects the well of the thumbnail that was clicked', async () => {
    await renderWall();
    const order = wellOrder();
    const layout = layoutOf(order.length, wallCanvas().clientWidth);
    const event = new MouseEvent('click', { bubbles: true });
    Object.defineProperty(event, 'offsetX', { value: tileX(1, layout) + 4 });
    Object.defineProperty(event, 'offsetY', { value: tileY(1, layout) + 4 });
    fireEvent(wallCanvas(), event);
    await waitFor(() =>
      expect(screen.getByTestId('state').textContent).toBe(`${order[1]}:0`)
    );
  });

  it('reports a broken history without drawing a wall', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockImplementation(() => Promise.resolve({ ok: false, status: 500 }))
    );
    render(withProviders(<WallOfLives />));
    expect(await screen.findByText(ru['wall.error'])).toBeTruthy();
    expect(document.querySelector('.wall-canvas')).toBeNull();
  });

  it('keeps the toolbar at or under the seven-control budget (R5)', async () => {
    const { container } = await renderWall();
    const toolbar = container.querySelector('.view-toolbar');
    expect(toolbar).not.toBeNull();
    const controls = toolbar!.querySelectorAll(
      ':scope > .view-toolbar-group > [role="group"], :scope > .view-toolbar-group > .popover-wrap, :scope > .view-toolbar-group > select, :scope > .view-toolbar-group > input'
    );
    expect(controls.length).toBeLessThanOrEqual(7);
  });

  it('renders ui/Legend inside the legend popover', async () => {
    await renderWall();
    openLegend();
    expect(screen.getByRole('group', { name: ru['wall.legend.title'] })).toBeTruthy();
    expect(screen.getByTestId('wall-legend-size')).toBeTruthy();
  });
});

describe('the wall spends the width the container offers', () => {
  it('widens the tiles to fill the row instead of leaving a ragged margin', () => {
    const container = 1089;
    const layout = layoutOf(WELL_COUNT, container);

    expect(layout.tileWidth).toBeGreaterThan(TILE_WIDTH);
    expect(Math.abs(container - layout.width)).toBeLessThanOrEqual(1);
  });

  it('keeps the tiles at their readable minimum when the container is cramped', () => {
    const layout = layoutOf(WELL_COUNT, TILE_WIDTH);

    expect(layout.tileWidth).toBe(TILE_WIDTH);
  });

  it('never lets one tile grow past the ceiling on a very wide screen', () => {
    const layout = layoutOf(2, 4000);

    expect(layout.tileWidth).toBeLessThanOrEqual(TILE_WIDTH_MAX);
  });

  it('maps a pointer back through the widened tile, not the default one', () => {
    const layout = layoutOf(WELL_COUNT, 1089);
    const lastStep = stepAt(layout.tileWidth, STEP_COUNT, layout.tileWidth);
    const firstStep = stepAt(0, STEP_COUNT, layout.tileWidth);

    expect(firstStep).toBe(0);
    expect(lastStep).toBe(STEP_COUNT - 1);
  });
});

describe('the wall spends the height the container offers', () => {
  it('grows the tiles to fill the room instead of leaving a dead band', () => {
    const rows = 7;
    const room = 720;
    const tall = layoutOf(WELL_COUNT, 1500, room);
    const short = layoutOf(WELL_COUNT, 1500, 0);

    expect(tall.tileHeight).toBeGreaterThan(short.tileHeight);
    expect(tall.height).toBeLessThanOrEqual(room);
    expect(tall.rows).toBeGreaterThan(0);
    expect(rows).toBeGreaterThan(0);
  });

  it('keeps the tiles at their readable minimum when the container is short', () => {
    const layout = layoutOf(WELL_COUNT, 1500, 10);

    expect(layout.tileHeight).toBe(TILE_HEIGHT);
  });

  it('never lets a tile grow past the ceiling on a very tall screen', () => {
    const layout = layoutOf(4, 1500, 4000);

    expect(layout.tileHeight).toBeLessThanOrEqual(TILE_HEIGHT_MAX);
  });

  it('reveals the wall on the same beat as the rest of the console', () => {
    const css = readFileSync(
      join(process.cwd(), 'src', 'views', 'WallOfLives', 'WallOfLives.css'),
      'utf-8'
    );
    const block = css.match(/\.wall-stage\s*\{[^}]*\}/)?.[0] ?? '';

    expect(block).toContain('var(--duration-drawer)');
    expect(block).not.toContain('--duration-reveal');
  });
});
