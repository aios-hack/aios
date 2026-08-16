import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import type { ReactNode } from 'react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { App } from '../../App';
import type { GraphFile } from '../../api/types';
import { dictionaries } from '../../i18n/dictionaries';
import { I18nProvider } from '../../i18n/I18nContext';
import { TimelineProvider } from '../../state/TimelineContext';
import { ThemeProvider } from '../../theme/ThemeContext';
import { WellCard } from '../WellCard';
import { LambdaGraph } from './LambdaGraph';

const { ru } = dictionaries;

const graphFixture: GraphFile = {
  window: { start: '2007-01-01', end: '2008-07-01' },
  nodes: [
    { id: 'I1', role: 'INJ', group: 'G1', x: 10, y: 10 },
    { id: 'P1', role: 'PROD', group: 'G1', x: 20, y: 14 },
    { id: 'I2', role: 'INJ', group: 'G2', x: 80, y: 70 },
    { id: 'P3', role: 'PROD', group: 'G2', x: 90, y: 76 }
  ],
  edges: [
    { injector: 'I1', producer: 'P1', weight: 0.9 },
    { injector: 'I2', producer: 'P3', weight: 0.8 },
    { injector: 'I1', producer: 'P3', weight: 0.05 }
  ],
  groups: [
    { id: 'G1', wells: ['I1', 'P1'] },
    { id: 'G2', wells: ['I2', 'P3'] }
  ],
  weight_range: { min: 0.05, max: 0.9 },
  meta: {
    lag_months: 3,
    amplitude: 0.2,
    stability: 0.77,
    rank: 2,
    condition_number: 4.25
  },
  layout: { size: 100, seed: 20070101 }
};

const timelineFixture = {
  model: 'Model_Z',
  t0: '2007-01-01',
  n_control_dates: 1,
  n_intervals: 0,
  wells: ['I1', 'P1', 'I2', 'P3'],
  steps: [
    {
      control_step: 0,
      date: '2007-01-01',
      terminal: false,
      field: {
        production: 100,
        injection: 80,
        compensation: 0.8,
        npv_cumulative: 1000,
        active_wells: 4
      },
      wells: ['I1', 'P1', 'I2', 'P3'].map((well) => ({
        well,
        availability: 'AVAILABLE',
        role: well.startsWith('I') ? 'INJ' : 'PROD',
        operating_status: 'OPEN',
        setpoint: 50,
        liquid_rate: 40,
        injection_rate: 0,
        bhp: 90,
        watercut: 0.5,
        fact_to_target: 0.8,
        cumulative_liquid: 100
      }))
    }
  ]
};

const withProviders = (node: ReactNode) => (
  <I18nProvider>
    <TimelineProvider>{node}</TimelineProvider>
  </I18nProvider>
);

const mockFetch = () => {
  vi.stubGlobal(
    'fetch',
    vi.fn((url: string) => {
      const payload = url.includes('graph')
        ? graphFixture
        : url.includes('timeline')
          ? timelineFixture
          : {};
      return Promise.resolve({ ok: true, json: () => Promise.resolve(payload) });
    })
  );
};

const renderGraph = async (node: ReactNode = <LambdaGraph />) => {
  const view = render(withProviders(node));
  await screen.findByTestId('lambda-graph-plot');
  return view;
};

const edges = (container: HTMLElement): Element[] => [
  ...container.querySelectorAll('[data-edge-id]')
];

const nodeFor = (container: HTMLElement, well: string): HTMLElement =>
  container.querySelector(`[data-well-id="${well}"]`) as HTMLElement;

beforeEach(() => {
  localStorage.clear();
  mockFetch();
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe('LambdaGraph', () => {
  it('renders a node per well and an edge per non-zero lambda link', async () => {
    const { container } = await renderGraph();
    expect(container.querySelectorAll('[data-well-id]')).toHaveLength(4);
    expect(edges(container)).toHaveLength(3);
    expect(nodeFor(container, 'I1').getAttribute('data-role')).toBe('INJ');
    expect(nodeFor(container, 'P1').getAttribute('data-role')).toBe('PROD');
  });

  it('shows the measurement window badge with formatted dates', async () => {
    await renderGraph();
    const badge = screen.getByTestId('lambda-graph-window');
    expect(badge.textContent).toContain('01.01.2007');
    expect(badge.textContent).toContain('01.07.2008');
  });

  it('hides edges below the threshold and reports the visible count', async () => {
    const { container } = await renderGraph();
    expect(edges(container)).toHaveLength(3);
    fireEvent.change(screen.getByLabelText(ru['graph.threshold.label']), {
      target: { value: '0.5' }
    });
    await waitFor(() => expect(edges(container)).toHaveLength(2));
    expect(screen.getByTestId('lambda-graph-count').textContent).toContain('2');
    expect(
      container.querySelector('[data-edge-id="I1-P3"]')
    ).toBeNull();
  });

  it('highlights the group and the lambda neighbours of the clicked well', async () => {
    const { container } = await renderGraph();
    fireEvent.click(nodeFor(container, 'I1'));
    await waitFor(() =>
      expect(nodeFor(container, 'I1').getAttribute('data-state')).toBe('selected')
    );
    expect(nodeFor(container, 'P1').getAttribute('data-state')).toBe('neighbour');
    expect(nodeFor(container, 'P3').getAttribute('data-state')).toBe('neighbour');
    expect(nodeFor(container, 'I2').getAttribute('data-state')).toBe('faded');
    const panel = screen.getByTestId('lambda-graph-selection');
    expect(panel.textContent).toContain('G1');
  });

  it('drops a neighbour from the highlight once the threshold hides its edge', async () => {
    const { container } = await renderGraph();
    fireEvent.change(screen.getByLabelText(ru['graph.threshold.label']), {
      target: { value: '0.5' }
    });
    fireEvent.click(nodeFor(container, 'I1'));
    await waitFor(() =>
      expect(nodeFor(container, 'P1').getAttribute('data-state')).toBe('neighbour')
    );
    expect(nodeFor(container, 'P3').getAttribute('data-state')).toBe('faded');
  });

  it('ignores a click that ends a pan drag', async () => {
    const { container } = await renderGraph();
    const plot = screen.getByTestId('lambda-graph-plot');
    const node = nodeFor(container, 'I1');
    fireEvent.pointerDown(plot, { clientX: 100, clientY: 100 });
    fireEvent.pointerMove(plot, { clientX: 180, clientY: 160 });
    fireEvent.pointerUp(plot, { clientX: 180, clientY: 160 });
    fireEvent.click(node);
    expect(screen.queryByTestId('lambda-graph-selection')).toBeNull();
    expect(nodeFor(container, 'I1').getAttribute('data-state')).toBe('plain');
  });

  it('opens the well card through the shared timeline context', async () => {
    const { container } = await renderGraph(
      <>
        <LambdaGraph />
        <WellCard />
      </>
    );
    fireEvent.click(nodeFor(container, 'P1'));
    await screen.findByText(ru['wellcard.title'].replace('{well}', 'P1'));
  });

  it('renders the lambda metadata panel', async () => {
    await renderGraph();
    expect(screen.getByText(ru['graph.meta.lag'])).toBeTruthy();
    expect(screen.getByText(ru['graph.meta.lagValue'].replace('{value}', '3'))).toBeTruthy();
    expect(screen.getByText(ru['graph.meta.stability'])).toBeTruthy();
  });

  it('lists every group in the legend', async () => {
    await renderGraph();
    expect(screen.getByText(ru['graph.legend.title'])).toBeTruthy();
    expect(screen.getByText('G1')).toBeTruthy();
    expect(screen.getByText('G2')).toBeTruthy();
  });

  it('shows an error message when the graph file is unavailable', async () => {
    vi.stubGlobal('fetch', vi.fn(() => Promise.resolve({ ok: false, json: () => Promise.resolve({}) })));
    render(withProviders(<LambdaGraph />));
    await screen.findByText(ru['graph.error']);
  });
});

describe('App tabs', () => {
  it('puts the influence graph first and opens it by default', async () => {
    const { container } = render(
      <ThemeProvider>
        <I18nProvider>
          <TimelineProvider>
            <App />
          </TimelineProvider>
        </I18nProvider>
      </ThemeProvider>
    );
    const tabs = [...container.querySelectorAll('.app-tab')].map((tab) => tab.textContent);
    expect(tabs).toEqual([
      ru['tab.graph'],
      ru['tab.map'],
      ru['tab.steps'],
      ru['tab.npv'],
      ru['tab.scenarios']
    ]);
    expect(container.querySelector('.app-tab')?.getAttribute('aria-pressed')).toBe('true');
    await screen.findByTestId('lambda-graph-plot');
  });
  it('keeps the wheel event to itself so the page does not zoom or scroll', async () => {
    // Без preventDefault браузер обрабатывает то же колесо сам: обычным
    // прокручивает страницу, а с Ctrl зумит её целиком вместе с графом.
    const { container } = await renderGraph();
    const plot = container.querySelector('[data-testid="lambda-graph-plot"]') as SVGSVGElement;

    const wheel = new WheelEvent('wheel', { deltaY: -120, cancelable: true, bubbles: true });
    plot.dispatchEvent(wheel);

    expect(wheel.defaultPrevented).toBe(true);
  });

  it('zooms the viewBox on wheel without touching anything outside the plot', async () => {
    const { container } = await renderGraph();
    const plot = container.querySelector('[data-testid="lambda-graph-plot"]') as SVGSVGElement;
    const before = plot.getAttribute('viewBox');

    plot.dispatchEvent(new WheelEvent('wheel', { deltaY: -120, cancelable: true, bubbles: true }));

    await waitFor(() => {
      expect(plot.getAttribute('viewBox')).not.toBe(before);
    });
    const [, , width] = (plot.getAttribute('viewBox') as string).split(' ').map(Number);
    const [, , widthBefore] = (before as string).split(' ').map(Number);
    expect(width).toBeLessThan(widthBefore);
  });

  it('keeps node size constant on screen while zooming so nodes actually separate', async () => {
    // Смысл зума: узлы обязаны разъезжаться, а не увеличиваться вместе с
    // расстояниями. Радиус в единицах viewBox поэтому падает при увеличении.
    const { container } = await renderGraph();
    const plot = container.querySelector('[data-testid="lambda-graph-plot"]') as SVGSVGElement;
    const radius = () =>
      Number(container.querySelector('[data-well-id="P1"] circle')?.getAttribute('r'));
    const before = radius();

    plot.dispatchEvent(new WheelEvent('wheel', { deltaY: -120, cancelable: true, bubbles: true }));

    await waitFor(() => {
      expect(radius()).toBeLessThan(before);
    });
  });

  it('draws the focus ring in its own geometry so it stays constant on screen', async () => {
    // CSS `outline` на SVG трактуется в единицах viewBox: при зуме обводка
    // раздувалась в кольцо на пол-экрана. Своя геометрия делится на масштаб.
    const { container } = await renderGraph();
    const plot = container.querySelector('[data-testid="lambda-graph-plot"]') as SVGSVGElement;
    const ring = () =>
      Number(container.querySelector('[data-well-id="P1"] .lambda-graph-focus')?.getAttribute('r'));

    expect(ring()).toBeGreaterThan(0);
    const before = ring();

    plot.dispatchEvent(new WheelEvent('wheel', { deltaY: -120, cancelable: true, bubbles: true }));

    await waitFor(() => {
      expect(ring()).toBeLessThan(before);
    });
  });
});
