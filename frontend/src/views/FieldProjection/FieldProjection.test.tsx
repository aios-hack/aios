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
import { edgeRelation } from './EdgeLayer';
import { easeInOut, fitLayout, lerp, placeNodes } from './interpolate';
import { projectNodes, weightBounds } from './model';
import { GLYPH_SCALE, hitRadius, nearestGaps, nodeOpacity, TAP_MIN_PX } from './NodeLayer';
import { FALLBACK_PLOT_SIZE_PX, unitsPerPixel } from './useProjection';
import {
  GROUP_GAP,
  MAX_STROKE,
  MIN_STROKE,
  NEIGHBOUR_GAP,
  PULSE_GAP,
  ringStroke
} from '../shared/SelectionRings';

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
  if (screen.queryByLabelText(ru['projection.threshold.label']) !== null) {
    return;
  }
  fireEvent.click(screen.getByLabelText(ru['toolbar.settings']));
};

const setBlend = (value: number) => {
  fireEvent.click(
    screen.getByRole('tab', {
      name: value >= 0.5 ? ru['projection.pole.graph'] : ru['projection.pole.map']
    })
  );
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
    stubMatchMedia(true);
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

    await waitFor(
      () => {
        expect(nodePosition(container, 'W1').x).toBeCloseTo(mapFit.get('W1')!.x, 6);
      },
      { timeout: 4000 }
    );
    CONNECTED.forEach((id) => {
      expect(nodePosition(container, id).x).toBeCloseTo(mapFit.get(id)!.x, 6);
      expect(nodePosition(container, id).y).toBeCloseTo(mapFit.get(id)!.y, 6);
    });
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

  it('caps the plot against the visible height, not just its width', () => {
    const block = css.match(/\.field-projection-canvas\s*\{[^}]*\}/)?.[0] ?? '';
    const cap = block.match(/max-height:\s*([^;]+);/)?.[1] ?? '';

    expect(cap).toContain('var(--size-plot-viewport)');
    expect(cap).not.toMatch(/\d+px/);
  });

  it('leaves the transport its own room instead of drawing under it', () => {
    const block = css.match(/\.field-projection-canvas\s*\{[^}]*\}/)?.[0] ?? '';
    const cap = block.match(/max-height:\s*([^;]+);/)?.[1] ?? '';

    expect(cap).toContain('calc(');
    expect(cap).toMatch(/-\s*var\(--space-/);
  });

  it('lets the graph spend the full width instead of a square well', () => {
    const block = css.match(/\.field-projection-plot\s*\{[^}]*\}/)?.[0] ?? '';

    expect(block).toContain('width: 100%');
    expect(block).not.toContain('aspect-ratio');
  });

  it('leaves the plot itself unframed so the graph reads on the page', () => {
    const block = css.match(/\.field-projection-plot\s*\{[^}]*\}/)?.[0] ?? '';

    expect(block).toContain('background: transparent');
    expect(block).toContain('border: 0');
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

describe('the projection animates its edges and drops the redundant slider', () => {
  const css = readFileSync(
    join(process.cwd(), 'src', 'views', 'FieldProjection', 'FieldProjection.css'),
    'utf-8'
  );

  it('fades an edge in rather than snapping it onto the plot', () => {
    const block = css.match(/\.field-projection-edges line\s*\{[^}]*\}/)?.[0] ?? '';

    expect(block).toContain('field-edge-in');
    expect(css).toContain('@keyframes field-edge-in');
  });

  it('eases the opacity and width as the lambda threshold moves', () => {
    const block = css.match(/\.field-projection-edges line\s*\{[^}]*\}/)?.[0] ?? '';

    expect(block).toContain('stroke-opacity');
    expect(block).toContain('stroke-width');
  });

  it('holds the edges still when the reader asked for less motion', () => {
    const reduced = css.match(
      /@media \(prefers-reduced-motion: reduce\)\s*\{[\s\S]*?\n\}/
    )?.[0] ?? '';

    expect(reduced).toContain('animation: none');
    expect(reduced).toContain('transition: none');
  });

  it('offers no blend slider now that the pole switch owns the morph', async () => {
    const { container } = await renderReady();
    fireEvent.click(screen.getByLabelText(ru['toolbar.settings']));

    expect(container.querySelector('#projection-blend')).toBeNull();
    expect(container.querySelector('#projection-threshold')).not.toBeNull();
  });
});

describe('the pointer target follows the screen, not the viewBox units', () => {
  it('converts a tap target from pixels using the axis the viewBox actually fits to', () => {
    const wide = unitsPerPixel({ width: 120, height: 120 }, { width: 2134, height: 773 });
    expect(wide).toBeCloseTo(120 / 773, 6);

    const tall = unitsPerPixel({ width: 120, height: 120 }, { width: 400, height: 1200 });
    expect(tall).toBeCloseTo(120 / 400, 6);
  });

  it('falls back to a declared plot size rather than dividing by zero before layout', () => {
    expect(unitsPerPixel({ width: 120, height: 120 }, null)).toBeCloseTo(
      120 / FALLBACK_PLOT_SIZE_PX,
      6
    );
    expect(
      unitsPerPixel({ width: 120, height: 120 }, { width: 0, height: 0 })
    ).toBeCloseTo(120 / FALLBACK_PLOT_SIZE_PX, 6);
  });

  it('spends the full 44px tap standard when the neighbours leave room', () => {
    const upp = 120 / 773;
    const roomy = hitRadius(0.5, upp, 40);
    expect(roomy).toBeCloseTo((TAP_MIN_PX / 2) * upp, 6);
    expect(roomy / upp).toBeCloseTo(TAP_MIN_PX / 2, 6);
  });

  it('never lets two hit areas overlap, which is what stole the click', () => {
    const upp = 120 / 773;
    const gap = 1.2;
    const crowded = hitRadius(0.2, upp, gap);
    expect(crowded).toBeLessThanOrEqual(gap / 2 + 1e-9);
    expect(crowded * 2).toBeLessThanOrEqual(gap + 1e-9);
  });

  it('never shrinks the target below the glyph the reader is aiming at', () => {
    expect(hitRadius(3, 120 / 773, 0.4)).toBe(3);
  });

  it('measures the nearest neighbour of every node so crowding is known per node', () => {
    const gaps = nearestGaps([
      { id: 'a', x: 0, y: 0, presence: 1, onlyMap: false, onlyGraph: false },
      { id: 'b', x: 3, y: 4, presence: 1, onlyMap: false, onlyGraph: false },
      { id: 'c', x: 0, y: 30, presence: 1, onlyMap: false, onlyGraph: false }
    ]);
    expect(gaps.get('a')).toBeCloseTo(5, 6);
    expect(gaps.get('b')).toBeCloseTo(5, 6);
    expect(gaps.get('c')).toBeCloseTo(Math.sqrt(3 * 3 + 26 * 26), 6);
    expect(nearestGaps([]).size).toBe(0);
  });

  it('clicks the well the reader aimed at instead of a crowded neighbour', async () => {
    const { container } = await renderReady();
    await waitFor(() =>
      expect(container.querySelectorAll('[data-well-id]')).toHaveLength(WELL_IDS.length)
    );

    for (const id of CONNECTED) {
      fireEvent.click(container.querySelector(`[data-well-id="${id}"]`) as SVGGElement);
      await waitFor(() =>
        expect(
          container
            .querySelector('[data-well-id][data-selected="true"]')
            ?.getAttribute('data-well-id')
        ).toBe(id)
      );
    }
  });
});

describe('the selection reads at a glance without shouting', () => {
  it('keeps every ring a small constant away from the glyph, not a multiple of it', () => {
    expect(GROUP_GAP).toBeLessThan(NEIGHBOUR_GAP);
    expect(NEIGHBOUR_GAP).toBeLessThan(PULSE_GAP);
    expect(PULSE_GAP).toBeLessThanOrEqual(2.5);
  });

  it('derives the stroke from the node radius and caps it so zooming cannot balloon it', () => {
    expect(ringStroke(0.1, 1)).toBe(MIN_STROKE);
    expect(ringStroke(100, 1)).toBe(MAX_STROKE);
    const mid = ringStroke(1.5, 1);
    expect(mid).toBeGreaterThanOrEqual(MIN_STROKE);
    expect(mid).toBeLessThanOrEqual(MAX_STROKE);
    expect(ringStroke(1.5, 0.6)).toBeLessThan(mid);
  });

  it('draws the glyphs smaller than the raw well radius so 103 nodes stay readable', () => {
    expect(GLYPH_SCALE).toBeLessThan(1);
    expect(GLYPH_SCALE).toBeGreaterThan(0.3);
  });

  it('pushes an unrelated well further back than one merely outside the layer', () => {
    expect(nodeOpacity(1, 'faded', false)).toBeLessThan(nodeOpacity(1, 'plain', true));
    expect(nodeOpacity(1, 'selected', false)).toBe(1);
    expect(nodeOpacity(0.5, 'plain', false)).toBeCloseTo(0.5, 6);
  });

  it('mutes the edges that miss the selection and lifts the ones that touch it', async () => {
    const { container } = await renderReady();
    await waitFor(() =>
      expect(container.querySelectorAll('[data-edge-id]')).toHaveLength(
        graphFixture.edges.length
      )
    );
    expect(
      [...container.querySelectorAll('[data-edge-id]')].every(
        (line) => line.getAttribute('data-relation') === 'plain'
      )
    ).toBe(true);

    fireEvent.click(container.querySelector('[data-well-id="W1"]') as SVGGElement);

    await waitFor(() =>
      expect(container.querySelectorAll('[data-relation="linked"]')).toHaveLength(2)
    );
  });

  it('marks an edge that touches neither end of the selection as muted', () => {
    const far = { injector: 'W9', producer: 'W8', weight: 0.5 };
    expect(edgeRelation(far, 'W1')).toBe('muted');
    expect(edgeRelation({ injector: 'W1', producer: 'W2', weight: 0.5 }, 'W1')).toBe(
      'linked'
    );
    expect(edgeRelation(far, null)).toBe('plain');
  });

  it('animates the rings in and holds them still under reduced motion', () => {
    const ringCss = readFileSync(
      join(process.cwd(), 'src', 'views', 'shared', 'SelectionRings.css'),
      'utf-8'
    );
    expect(ringCss).toContain('@keyframes selection-ring-in');
    expect(ringCss).toContain('@keyframes selection-pulse-in');
    const reduced =
      ringCss.match(/@media \(prefers-reduced-motion: reduce\)\s*\{[\s\S]*?\n\}/)?.[0] ?? '';
    expect(reduced).toContain('animation: none');
  });
});

describe('the layer switch animates the nodes it turns on and off', () => {
  const css = readFileSync(
    join(process.cwd(), 'src', 'views', 'FieldProjection', 'FieldProjection.css'),
    'utf-8'
  );

  it('gives a node an explicit enter AND an explicit exit keyframe', () => {
    expect(css).toContain('@keyframes field-node-in');
    expect(css).toContain('@keyframes field-node-out');
  });

  it('drives them off the same data-active flag the filter already sets', () => {
    expect(css).toMatch(/\[data-active='true'\][\s\S]*?field-node-in/);
    expect(css).toMatch(/\[data-active='false'\][\s\S]*?field-node-out/);
  });

  it('builds the motion from opacity and scale, never a banned shadow or lift (V11)', () => {
    expect(css).not.toMatch(/var\(--shadow/);
    expect(css).not.toMatch(/translateY\(-\d+px\)/);
  });
});

describe('the legend explains the picture a new engineer is looking at', () => {
  it('names both node shapes, the size and the edge encodings', async () => {
    await renderReady();
    fireEvent.click(screen.getByLabelText(ru['toolbar.legend']));

    for (const key of [
      'projection.legend.shape.producer',
      'projection.legend.shape.injector',
      'projection.legend.size',
      'projection.legend.edge.width',
      'projection.legend.edge.positive',
      'projection.legend.edge.negative',
      'projection.legend.pole.explain',
      'projection.legend.selection'
    ]) {
      expect(screen.getByText(ru[key]), key).toBeTruthy();
    }
  });

  it('shows a colour swatch for each edge sign rather than describing it in prose alone', async () => {
    const { container } = await renderReady();
    fireEvent.click(screen.getByLabelText(ru['toolbar.legend']));

    expect(container.querySelectorAll('.legend-swatch').length).toBeGreaterThanOrEqual(2);
  });
});
