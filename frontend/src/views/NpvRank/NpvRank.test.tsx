import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { ReactNode } from 'react';
import type { NpvFile, TimelineFile } from '../../api/types';
import { dictionaries } from '../../i18n/dictionaries';
import { I18nProvider } from '../../i18n/I18nContext';
import { TimelineProvider } from '../../state/TimelineContext';
import { ConsoleInspector } from '../../ui/Inspector';
import { NpvRank } from './NpvRank';

const { ru } = dictionaries;

const npvFixture: NpvFile = {
  wells: [
    { well: '10', pre_tax: 50, with_allocated_tax: 40 },
    { well: '11', pre_tax: 150, with_allocated_tax: 120 },
    { well: '12', pre_tax: -30, with_allocated_tax: -30 }
  ],
  total: { pre_tax: 170, with_allocated_tax: 130 },
  npv_methodology: 130
};

const timelineFixture: TimelineFile = {
  model: 'Model_Z',
  t0: '2007-01-01',
  n_control_dates: 1,
  n_intervals: 0,
  wells: ['10', '11', '12'],
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
        active_wells: 3
      },
      wells: ['10', '11', '12'].map((well) => ({
        well,
        availability: 'AVAILABLE',
        role: 'PROD',
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
      const payload = url.includes('npv')
        ? npvFixture
        : url.includes('timeline')
          ? timelineFixture
          : {};
      return Promise.resolve({ ok: true, json: () => Promise.resolve(payload) });
    })
  );
};

const rowIds = (container: HTMLElement): (string | null)[] =>
  [...container.querySelectorAll('tbody tr')].map((row) =>
    row.getAttribute('data-well-id')
  );

const rowFor = (container: HTMLElement, well: string): HTMLElement => {
  const row = container.querySelector(`tbody tr[data-well-id="${well}"]`);
  expect(row).not.toBeNull();
  return row as HTMLElement;
};

const renderView = async (node: ReactNode) => {
  const view = render(withProviders(node));
  await waitFor(() =>
    expect(view.container.querySelectorAll('tbody tr')).toHaveLength(3)
  );
  return view;
};

beforeEach(() => {
  localStorage.clear();
  mockFetch();
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe('NpvRank', () => {
  it('renders wells sorted by pre-tax contribution descending by default', async () => {
    const { container } = await renderView(<NpvRank />);
    expect(rowIds(container)).toEqual(['11', '10', '12']);
    expect(screen.getByText(ru['npv.column.preTax'])).toBeTruthy();
    expect(screen.getByText(ru['npv.badge.preTax'])).toBeTruthy();
    expect(rowFor(container, '11').textContent).toContain('150');
  });

  it('toggles sort direction on header click', async () => {
    const { container } = await renderView(<NpvRank />);
    const valueHeader = () =>
      container.querySelectorAll('.npv-sort-button')[1] as HTMLElement;
    fireEvent.click(valueHeader());
    expect(rowIds(container)).toEqual(['12', '10', '11']);
    fireEvent.click(valueHeader());
    expect(rowIds(container)).toEqual(['11', '10', '12']);
  });

  it('sorts by well number and keeps numeric order', async () => {
    const { container } = await renderView(<NpvRank />);
    const wellHeader = () =>
      container.querySelectorAll('.npv-sort-button')[0] as HTMLElement;
    fireEvent.click(wellHeader());
    expect(rowIds(container)).toEqual(['10', '11', '12']);
    fireEvent.click(wellHeader());
    expect(rowIds(container)).toEqual(['12', '11', '10']);
  });

  it('switches the tax label, changing the column and the badge', async () => {
    const { container } = await renderView(<NpvRank />);
    fireEvent.click(screen.getByRole('tab', { name: ru['npv.mode.withTax'] }));
    expect(screen.getByText(ru['npv.column.withTax'])).toBeTruthy();
    expect(screen.getByText(ru['npv.badge.withTax'])).toBeTruthy();
    expect(screen.queryByText(ru['npv.column.preTax'])).toBeNull();
    expect(screen.queryByText(ru['npv.badge.preTax'])).toBeNull();
    expect(rowFor(container, '11').textContent).toContain('120');
    expect(rowFor(container, '11').textContent).not.toContain('150');
  });

  it('marks negative contributions with the danger class', async () => {
    const { container } = await renderView(<NpvRank />);
    expect(rowFor(container, '12').querySelector('.npv-danger')).not.toBeNull();
    expect(rowFor(container, '12').querySelector('.npv-bar-danger')).not.toBeNull();
    expect(rowFor(container, '11').querySelector('.npv-danger')).toBeNull();
  });

  it('opens the well card when a row is clicked', async () => {
    const { container } = await renderView(
      <>
        <NpvRank />
        <ConsoleInspector />
      </>
    );
    fireEvent.click(rowFor(container, '12'));
    await screen.findByText(ru['wellcard.title'].replace('{well}', '12'));
    expect(screen.getByText(ru['wellcard.params.title'])).toBeTruthy();
  });
});

describe('NpvRank row reveal', () => {
  it('numbers rows in render order so the stagger follows the sort', async () => {
    const { container } = await renderView(<NpvRank />);
    const indices = [...container.querySelectorAll('tbody tr')].map((row) =>
      (row as HTMLElement).style.getPropertyValue('--npv-row-index')
    );
    expect(indices).toEqual(['0', '1', '2']);
  });

  it('renumbers rows after a re-sort so the reveal never runs backwards', async () => {
    const { container } = await renderView(<NpvRank />);
    const valueHeader = () =>
      container.querySelectorAll('.npv-sort-button')[1] as HTMLElement;
    fireEvent.click(valueHeader());

    const rows = [...container.querySelectorAll('tbody tr')];
    expect(rows.map((row) => row.getAttribute('data-well-id'))).toEqual([
      '12',
      '10',
      '11'
    ]);
    expect(
      rows.map((row) => (row as HTMLElement).style.getPropertyValue('--npv-row-index'))
    ).toEqual(['0', '1', '2']);
  });

  it('caps the stagger index so a long table does not delay its last rows', async () => {
    const many: NpvFile = {
      wells: Array.from({ length: 40 }, (_, index) => ({
        well: String(index),
        pre_tax: 100 - index,
        with_allocated_tax: 90 - index
      })),
      total: { pre_tax: 1000, with_allocated_tax: 900 },
      npv_methodology: 900
    };
    vi.stubGlobal(
      'fetch',
      vi.fn((url: string) =>
        Promise.resolve({
          ok: true,
          json: () =>
            Promise.resolve(url.includes('timeline') ? timelineFixture : many)
        })
      )
    );

    const view = render(withProviders(<NpvRank />));
    await waitFor(() =>
      expect(view.container.querySelectorAll('tbody tr')).toHaveLength(40)
    );

    const indices = [...view.container.querySelectorAll('tbody tr')].map((row) =>
      Number((row as HTMLElement).style.getPropertyValue('--npv-row-index'))
    );
    const max = Math.max(...indices);
    expect(max).toBeLessThanOrEqual(16);
    expect(indices.filter((value) => value === max).length).toBeGreaterThan(1);
    expect(indices[indices.length - 1]).toBe(max);
  });
});
