import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { act } from 'react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { ReactNode } from 'react';
import type { GraphFile, NpvFile, TimelineFile, WellsFile } from '../../api/types';
import { dictionaries } from '../../i18n/dictionaries';
import { I18nProvider } from '../../i18n/I18nContext';
import { TimelineProvider } from '../../state/TimelineContext';
import { ThemeProvider } from '../../theme/ThemeContext';
import { FieldProjection } from './FieldProjection';
import { easeInOut, fitLayout, lerp, placeNodes } from './interpolate';
import { projectNodes, weightBounds } from './model';

const { ru } = dictionaries;

const WELL_IDS = ['W1', 'W2', 'W3', 'W4'];
const CONNECTED = WELL_IDS.slice(0, 3);

const wellsFixture: WellsFile = {
  grid: { ni: 40, nj: 60, nk: 5 },
  layers: [
    { id: 1, k_min: 1, k_max: 3 },
    { id: 2, k_min: 4, k_max: 5 }
  ],
  wells: WELL_IDS.map((id, index) => ({
    id,
    i: 4 + index * 8,
    j: 6 + index * 4,
    completions: [[1, 2]],
    layers: index === 0 ? [2] : [1]
  }))
};

const graphFixture: GraphFile = {
  window: { start: '2007-01-01', end: '2009-01-01' },
  nodes: CONNECTED.map((id, index) => ({
    id,
    role: index === 0 ? 'INJ' : 'PROD',
    group: null,
    x: index * 30,
    y: 90 - index * 20
  })),
  edges: [
    { injector: 'W1', producer: 'W2', weight: 0.8 },
    { injector: 'W1', producer: 'W3', weight: 0.3 }
  ],
  groups: [],
  weight_range: { min: 0.3, max: 0.8 },
  meta: { lag_months: 2, amplitude: 1, stability: 0.99, rank: 3, condition_number: 2 },
  layout: { size: 100, seed: 1 }
};

const timelineFixture: TimelineFile = {
  model: 'Model_Z',
  t0: '2007-01-01',
  n_control_dates: 2,
  n_intervals: 1,
  wells: WELL_IDS,
  steps: [0, 1].map((k) => ({
    control_step: k,
    date: `${2007 + k}-01-01`,
    terminal: k === 1,
    field: {
      production: 100,
      injection: 90,
      compensation: 0.9,
      npv_cumulative: 1000 * (k + 1),
      active_wells: WELL_IDS.length
    },
    wells: WELL_IDS.map((well, index) => ({
      well,
      availability: 'AVAILABLE' as const,
      role: index === 0 ? ('INJ' as const) : ('PROD' as const),
      operating_status: 'OPEN' as const,
      setpoint: 100,
      liquid_rate: 40 + 10 * index,
      injection_rate: 120,
      bhp: 90,
      watercut: 0.2 * index,
      fact_to_target: 0.9,
      cumulative_liquid: 500
    }))
  }))
};

const npvFixture: NpvFile = {
  wells: WELL_IDS.map((well, index) => ({
    well,
    pre_tax: 100 * (index + 1),
    with_allocated_tax: 90 * (index + 1)
  })),
  total: { pre_tax: 1000, with_allocated_tax: 900 },
  npv_methodology: 900
};

const withProviders = (node: ReactNode) => (
  <I18nProvider>
    <ThemeProvider>
      <TimelineProvider>{node}</TimelineProvider>
    </ThemeProvider>
  </I18nProvider>
);

const mockRoutes = () => {
  vi.stubGlobal(
    'fetch',
    vi.fn().mockImplementation((url: string) => {
      const payload = url.includes('timeline')
        ? timelineFixture
        : url.includes('npv')
          ? npvFixture
          : url.includes('graph')
            ? graphFixture
            : wellsFixture;
      return Promise.resolve({ ok: true, json: () => Promise.resolve(payload) });
    })
  );
};

const stubMatchMedia = (reduced: boolean) => {
  vi.stubGlobal(
    'matchMedia',
    vi.fn((query: string) => ({
      matches: reduced && query.includes('prefers-reduced-motion'),
      media: query,
      onchange: null,
      addListener: vi.fn(),
      removeListener: vi.fn(),
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
      dispatchEvent: vi.fn()
    }))
  );
};

let frames: FrameRequestCallback[] = [];

const stubRaf = () => {
  frames = [];
  vi.stubGlobal('requestAnimationFrame', (callback: FrameRequestCallback) => {
    frames.push(callback);
    return frames.length;
  });
  vi.stubGlobal('cancelAnimationFrame', vi.fn());
};

const runFrame = (now: number) => {
  const pending = frames;
  frames = [];
  act(() => {
    for (const callback of pending) {
      callback(now);
    }
  });
};

const nodePosition = (container: HTMLElement, id: string): { x: number; y: number } => {
  const node = container.querySelector<SVGGElement>(`[data-well-id="${id}"]`);
  if (node === null) {
    throw new Error(`no node ${id}`);
  }
  return { x: Number(node.dataset.x), y: Number(node.dataset.y) };
};

const edgeOpacities = (container: HTMLElement): number[] =>
  [...container.querySelectorAll<SVGLineElement>('[data-edge-id]')].map((line) =>
    Number(line.dataset.opacity)
  );

const renderReady = async () => {
  const view = render(withProviders(<FieldProjection />));
  await waitFor(() =>
    expect(view.container.querySelector('.field-projection-plot')).not.toBeNull()
  );
  return view;
};

const openSettings = () => {
  if (screen.queryByLabelText(ru['projection.blend.label']) !== null) {
    return;
  }
  fireEvent.click(screen.getByLabelText(ru['toolbar.settings']));
};

const setBlend = (value: number) => {
  openSettings();
  const slider = screen.getByLabelText(ru['projection.blend.label']);
  fireEvent.change(slider, { target: { value: String(value) } });
};

beforeEach(() => {
  localStorage.clear();
  mockRoutes();
  stubMatchMedia(false);
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe('fitLayout', () => {
  const box = { x: 0, y: 0, width: 100, height: 100 };

  it('keeps proportions and centres the shorter axis inside the box', () => {
    const fitted = fitLayout(
      [
        { id: 'a', x: 0, y: 0 },
        { id: 'b', x: 20, y: 10 }
      ],
      box
    );
    expect(fitted.get('a')).toEqual({ x: 0, y: 25 });
    expect(fitted.get('b')).toEqual({ x: 100, y: 75 });
  });

  it('maps both layouts into the same box whatever their own units are', () => {
    const map = fitLayout(
      [
        { id: 'a', x: 5, y: 7 },
        { id: 'b', x: 76, y: 93 }
      ],
      box
    );
    const graph = fitLayout(
      [
        { id: 'a', x: 0, y: 0 },
        { id: 'b', x: 94.04, y: 100 }
      ],
      box
    );
    for (const fitted of [map, graph]) {
      for (const point of fitted.values()) {
        expect(point.x).toBeGreaterThanOrEqual(box.x);
        expect(point.x).toBeLessThanOrEqual(box.x + box.width);
        expect(point.y).toBeGreaterThanOrEqual(box.y);
        expect(point.y).toBeLessThanOrEqual(box.y + box.height);
      }
    }
  });

  it('places a degenerate layout at the centre instead of dividing by zero', () => {
    const fitted = fitLayout(
      [
        { id: 'a', x: 3, y: 3 },
        { id: 'b', x: 3, y: 3 }
      ],
      box
    );
    expect(fitted.get('a')).toEqual({ x: 50, y: 50 });
    expect(fitLayout([], box).size).toBe(0);
  });
});

describe('projectNodes', () => {
  it('keeps every well of both layouts, taking the roster from the data', () => {
    const projected = projectNodes(wellsFixture, graphFixture);
    expect(projected).toHaveLength(WELL_IDS.length);
    expect(projected.filter((node) => node.graph === null)).toHaveLength(
      WELL_IDS.length - CONNECTED.length
    );
    expect(projected.every((node) => node.map !== null)).toBe(true);
  });

  it('reads the lambda bounds off the edges instead of hard-coded limits', () => {
    const bounds = weightBounds(graphFixture.edges);
    expect(bounds.min).toBeCloseTo(0.3, 6);
    expect(bounds.max).toBeGreaterThan(0.8);
    expect(weightBounds([])).toEqual({ min: 0, max: 0 });
  });
});

describe('placeNodes', () => {
  const nodes = [
    { id: 'both', map: { x: 0, y: 0 }, graph: { x: 10, y: 20 } },
    { id: 'mapOnly', map: { x: 4, y: 4 }, graph: null },
    { id: 'graphOnly', map: null, graph: { x: 8, y: 8 } }
  ];

  it('puts every node on its map position at t = 0', () => {
    const placed = placeNodes(nodes, 0);
    expect(placed[0]).toMatchObject({ x: 0, y: 0, presence: 1 });
    expect(placed[1]).toMatchObject({ x: 4, y: 4, presence: 1 });
  });

  it('puts every node on its graph position at t = 1', () => {
    const placed = placeNodes(nodes, 1);
    expect(placed[0]).toMatchObject({ x: 10, y: 20, presence: 1 });
    expect(placed[2]).toMatchObject({ x: 8, y: 8, presence: 1 });
  });

  it('leaves a node between the two layouts at t = 0.5', () => {
    const placed = placeNodes(nodes, 0.5);
    expect(placed[0].x).toBe(lerp(0, 10, 0.5));
    expect(placed[0].y).toBe(lerp(0, 20, 0.5));
    expect(placed[0].x).toBeGreaterThan(0);
    expect(placed[0].x).toBeLessThan(10);
  });

  it('fades a node that only one layout knows instead of dropping it', () => {
    expect(placeNodes(nodes, 1)[1]).toMatchObject({ presence: 0, onlyMap: true });
    expect(placeNodes(nodes, 0)[2]).toMatchObject({ presence: 0, onlyGraph: true });
    expect(placeNodes(nodes, 0.5)[1].presence).toBeCloseTo(0.5);
    expect(placeNodes(nodes, 1)).toHaveLength(nodes.length);
  });

  it('eases the travel without leaving the unit interval', () => {
    expect(easeInOut(0)).toBe(0);
    expect(easeInOut(1)).toBe(1);
    expect(easeInOut(0.5)).toBeCloseTo(0.5);
    expect(easeInOut(-1)).toBe(0);
    expect(easeInOut(2)).toBe(1);
  });
});

describe('FieldProjection view', () => {
  it('draws the graph layout at t = 1 by default (KS1) and the map layout at t = 0', async () => {
    const { container } = await renderReady();
    await waitFor(() =>
      expect(container.querySelectorAll('[data-well-id]')).toHaveLength(WELL_IDS.length)
    );

    const box = { x: 0, y: 0, width: 100, height: 100 };
    const mapFit = fitLayout(
      wellsFixture.wells.map((well) => ({ id: well.id, x: well.i, y: well.j })),
      box
    );
    const graphFit = fitLayout(
      graphFixture.nodes.map((node) => ({ id: node.id, x: node.x, y: node.y })),
      box
    );
    CONNECTED.forEach((id) => {
      expect(nodePosition(container, id).x).toBeCloseTo(graphFit.get(id)!.x, 6);
      expect(nodePosition(container, id).y).toBeCloseTo(graphFit.get(id)!.y, 6);
    });

    setBlend(0);

    await waitFor(() => {
      expect(nodePosition(container, 'W1').x).toBeCloseTo(mapFit.get('W1')!.x, 6);
    });
    CONNECTED.forEach((id) => {
      expect(nodePosition(container, id).x).toBeCloseTo(mapFit.get(id)!.x, 6);
      expect(nodePosition(container, id).y).toBeCloseTo(mapFit.get(id)!.y, 6);
    });
  });

  it('holds the nodes between the two layouts at t = 0.5', async () => {
    const { container } = await renderReady();
    await waitFor(() =>
      expect(container.querySelectorAll('[data-well-id]')).toHaveLength(WELL_IDS.length)
    );
    const atOne = nodePosition(container, 'W3');

    setBlend(0);
    await waitFor(() => expect(nodePosition(container, 'W3').x).not.toBeCloseTo(atOne.x, 6));
    const atZero = nodePosition(container, 'W3');

    setBlend(0.5);
    await waitFor(() =>
      expect(nodePosition(container, 'W3').x).toBeCloseTo((atZero.x + atOne.x) / 2, 6)
    );
    const half = nodePosition(container, 'W3');
    expect(half.y).toBeCloseTo((atZero.y + atOne.y) / 2, 6);
    expect(Math.min(atZero.x, atOne.x)).toBeLessThan(half.x);
    expect(Math.max(atZero.x, atOne.x)).toBeGreaterThan(half.x);
  });

  it('shows every lambda edge visible by default and hides them on the bare map', async () => {
    const { container } = await renderReady();
    await waitFor(() =>
      expect(container.querySelectorAll('[data-edge-id]')).toHaveLength(
        graphFixture.edges.length
      )
    );
    expect(edgeOpacities(container).every((value) => value > 0)).toBe(true);

    setBlend(0);

    await waitFor(() =>
      expect(edgeOpacities(container).every((value) => value === 0)).toBe(true)
    );
  });

  it('counts the wells that carry no measured connectivity', async () => {
    await renderReady();
    fireEvent.click(screen.getByLabelText(ru['toolbar.legend']));
    await screen.findByText(
      ru['projection.withoutConnectivity'].replace(
        '{count}',
        String(WELL_IDS.length - CONNECTED.length)
      )
    );
  });

  it('animates the travel over several frames when motion is allowed', async () => {
    stubRaf();
    const { container } = await renderReady();
    await waitFor(() =>
      expect(container.querySelectorAll('[data-well-id]')).toHaveLength(WELL_IDS.length)
    );
    const start = nodePosition(container, 'W3');

    fireEvent.click(screen.getByText(ru['projection.pole.map']));
    expect(frames.length).toBeGreaterThan(0);

    runFrame(performance.now() + 400);
    const midway = nodePosition(container, 'W3');
    expect(midway.x).not.toBeCloseTo(start.x, 6);
    expect(frames.length).toBeGreaterThan(0);
  });

  it('jumps straight to the target when the user asked for reduced motion', async () => {
    stubMatchMedia(true);
    stubRaf();
    const { container } = await renderReady();
    await waitFor(() =>
      expect(container.querySelectorAll('[data-well-id]')).toHaveLength(WELL_IDS.length)
    );
    const box = { x: 0, y: 0, width: 100, height: 100 };
    const mapFit = fitLayout(
      wellsFixture.wells.map((well) => ({ id: well.id, x: well.i, y: well.j })),
      box
    );

    fireEvent.click(screen.getByText(ru['projection.pole.map']));

    await waitFor(() =>
      expect(nodePosition(container, 'W3').x).toBeCloseTo(mapFit.get('W3')!.x, 6)
    );
    expect(frames).toHaveLength(0);
    openSettings();
    expect(screen.getByTestId('field-projection-t').textContent).toBe('0.00');
  });

  it('reports a russian error when a layout cannot be loaded', async () => {
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new Error('network')));
    render(withProviders(<FieldProjection />));
    await screen.findByText(ru['projection.error']);
  });

  it('keeps the toolbar at or under the seven-control budget (R5)', async () => {
    const { container } = await renderReady();
    const toolbar = container.querySelector('.view-toolbar');
    expect(toolbar).not.toBeNull();
    const controls = toolbar!.querySelectorAll(
      ':scope > .view-toolbar-group > [role="group"], :scope > .view-toolbar-group > .popover-wrap, :scope > .view-toolbar-group > select, :scope > .view-toolbar-group > input'
    );
    expect(controls.length).toBeLessThanOrEqual(7);
  });

  it('renders ui/Legend inside the legend popover', async () => {
    await renderReady();
    fireEvent.click(screen.getByLabelText(ru['toolbar.legend']));
    expect(screen.getByRole('group', { name: ru['projection.legend.title'] })).toBeTruthy();
  });

  it('adjusts the lambda threshold from the settings popover and hides thin edges', async () => {
    const { container } = await renderReady();
    await waitFor(() =>
      expect(container.querySelectorAll('[data-edge-id]')).toHaveLength(
        graphFixture.edges.length
      )
    );
    openSettings();
    const thresholdSlider = screen.getByLabelText(ru['projection.threshold.label']);
    fireEvent.change(thresholdSlider, { target: { value: '0.5' } });

    await waitFor(() =>
      expect(container.querySelectorAll('[data-edge-id]')).toHaveLength(1)
    );
  });

  it('builds the layer filter options from the wells file, not a literal', async () => {
    await renderReady();
    expect(screen.getByText(ru['projection.layer.all'])).toBeTruthy();
    expect(screen.getByText(ru['projection.layer.item'].replace('{id}', '1')).textContent).toBe(
      'Пласт 1'
    );
    expect(screen.getByText(ru['projection.layer.item'].replace('{id}', '2')).textContent).toBe(
      'Пласт 2'
    );
  });

  it('dims wells outside the selected layer without removing them from the DOM', async () => {
    const { container } = await renderReady();
    await waitFor(() =>
      expect(container.querySelectorAll('[data-well-id]')).toHaveLength(WELL_IDS.length)
    );

    fireEvent.click(
      screen.getByText(ru['projection.layer.item'].replace('{id}', '1'))
    );

    await waitFor(() =>
      expect(container.querySelectorAll('[data-well-id][data-active="false"]')).toHaveLength(1)
    );
    expect(container.querySelectorAll('[data-well-id]')).toHaveLength(WELL_IDS.length);
    expect(container.querySelector('[data-well-id="W1"]')?.getAttribute('data-active')).toBe(
      'false'
    );
    expect(container.querySelector('[data-well-id="W2"]')?.getAttribute('data-active')).toBe(
      'true'
    );

    fireEvent.click(screen.getByText(ru['projection.layer.all']));
    await waitFor(() =>
      expect(container.querySelectorAll('[data-well-id][data-active="false"]')).toHaveLength(0)
    );
    expect(container.querySelectorAll('[data-well-id]')).toHaveLength(WELL_IDS.length);
  });

  it('adds a shown-count and dimmed note to the legend once a layer is filtered', async () => {
    await renderReady();
    fireEvent.click(
      screen.getByText(ru['projection.layer.item'].replace('{id}', '1'))
    );
    fireEvent.click(screen.getByLabelText(ru['toolbar.legend']));
    await screen.findByText(
      ru['projection.shown'].replace('{shown}', '3').replace('{total}', '4')
    );
    expect(screen.getByText(ru['projection.dim'])).toBeTruthy();
  });

  it('keeps well selection and lambda-neighbour highlighting working while filtered by layer', async () => {
    const { container } = await renderReady();
    await waitFor(() =>
      expect(container.querySelectorAll('[data-well-id]')).toHaveLength(WELL_IDS.length)
    );

    fireEvent.click(
      screen.getByText(ru['projection.layer.item'].replace('{id}', '1'))
    );

    const w1 = container.querySelector('[data-well-id="W1"]') as SVGGElement;
    fireEvent.click(w1);

    await waitFor(() =>
      expect(
        container.querySelector('[data-well-id="W1"]')?.getAttribute('data-highlight')
      ).toBe('selected')
    );
    expect(
      container.querySelector('[data-well-id="W2"]')?.getAttribute('data-highlight')
    ).toBe('neighbour');
    expect(
      container.querySelector('[data-well-id="W3"]')?.getAttribute('data-highlight')
    ).toBe('neighbour');
  });
});

describe('the map fits the screen instead of forcing a scroll', () => {
  const css = readFileSync(join(process.cwd(), 'src', 'views', 'FieldProjection', 'FieldProjection.css'), 'utf-8');
  const consoleCss = readFileSync(join(process.cwd(), 'src', 'app', 'console.css'), 'utf-8');

  it('caps the square plot against the visible height, not just its width', () => {
    const block = css.match(/\.field-projection-canvas\s*\{[^}]*\}/)?.[0] ?? '';
    expect(block).toContain('max-height: var(--size-plot-viewport)');
  });

  it('measures that ceiling from the chrome it actually sits under', () => {
    const value = consoleCss.match(/--size-plot-viewport:\s*([^;]+);/)?.[1] ?? '';
    expect(value).toContain('100vh');
    expect(value).toContain('var(--h-header)');
    expect(value).toContain('var(--h-axis-space, var(--h-timeaxis))');
  });

  it('spends no literal pixel heights on that ceiling', () => {
    const value = consoleCss.match(/--size-plot-viewport:\s*([^;]+);/)?.[1] ?? '';
    expect(value).not.toMatch(/\d+px/);
  });
});
