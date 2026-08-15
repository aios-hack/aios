import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { ReactNode } from 'react';
import type { TimelineFile, TimelineStep, TimelineWellRow } from '../../api/types';
import en from '../../i18n/en.json';
import { I18nProvider } from '../../i18n/I18nContext';
import ru from '../../i18n/ru.json';
import { Timeline } from './Timeline';

const makeWells = (k: number, terminal: boolean): TimelineWellRow[] => [
  {
    well: '10',
    availability: 'AVAILABLE',
    role: 'INJ',
    operating_status: 'OPEN',
    setpoint: 160,
    liquid_rate: 0,
    injection_rate: 140 + k,
    bhp: 250,
    watercut: terminal ? null : 0
  },
  {
    well: '11',
    availability: 'AVAILABLE',
    role: 'PROD',
    operating_status: 'OPEN',
    setpoint: 50,
    liquid_rate: 70 + 10 * k,
    injection_rate: 0,
    bhp: 91,
    watercut: terminal ? null : 0.5
  },
  {
    well: '14',
    availability: 'NOT_COMMISSIONED',
    role: 'NONE',
    operating_status: 'SHUT',
    setpoint: 0,
    liquid_rate: 0,
    injection_rate: 0,
    bhp: 0,
    watercut: terminal ? null : 0
  }
];

const makeStep = (k: number, terminal: boolean): TimelineStep => ({
  control_step: k,
  date: `2007-0${k + 1}-01`,
  terminal,
  field: {
    production: terminal ? null : 2000 + k,
    injection: terminal ? null : 1500 + k,
    compensation: terminal ? null : 0.75,
    npv_cumulative: 1000 * (k + 1),
    active_wells: 2
  },
  wells: makeWells(k, terminal)
});

const fixture: TimelineFile = {
  model: 'Model_Z',
  t0: '2007-01-01',
  n_control_dates: 4,
  n_intervals: 3,
  wells: ['10', '11', '14'],
  steps: [makeStep(0, false), makeStep(1, false), makeStep(2, false), makeStep(3, true)]
};

const withProviders = (node: ReactNode) => <I18nProvider>{node}</I18nProvider>;

const mockFetchWith = (payload: TimelineFile) => {
  vi.stubGlobal(
    'fetch',
    vi.fn().mockResolvedValue({ ok: true, json: () => Promise.resolve(payload) })
  );
};

const rowFor = (container: HTMLElement, well: string): HTMLElement => {
  const row = container.querySelector(`tr[data-well-id="${well}"]`);
  expect(row).not.toBeNull();
  return row as HTMLElement;
};

beforeEach(() => {
  localStorage.clear();
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe('Timeline', () => {
  it('renders a sorted well table for the first step', async () => {
    mockFetchWith(fixture);
    const { container } = render(withProviders(<Timeline />));
    await waitFor(() =>
      expect(container.querySelectorAll('tbody tr')).toHaveLength(3)
    );
    const ids = [...container.querySelectorAll('tbody tr')].map((row) =>
      row.getAttribute('data-well-id')
    );
    expect(ids).toEqual(['10', '11', '14']);
    expect(rowFor(container, '11').textContent).toContain('70');
    expect(screen.getByText(ru['steps.field.activeWells'])).toBeTruthy();
  });

  it('updates the table when the slider moves', async () => {
    mockFetchWith(fixture);
    const { container } = render(withProviders(<Timeline />));
    await waitFor(() =>
      expect(container.querySelector('input[type="range"]')).not.toBeNull()
    );
    const slider = container.querySelector('input[type="range"]') as HTMLInputElement;
    fireEvent.change(slider, { target: { value: '1' } });
    expect(rowFor(container, '11').textContent).toContain('80');
    expect(rowFor(container, '11').textContent).not.toContain('70');
  });

  it('marks the terminal step with a badge and dashes', async () => {
    mockFetchWith(fixture);
    const { container } = render(withProviders(<Timeline />));
    await waitFor(() =>
      expect(container.querySelector('input[type="range"]')).not.toBeNull()
    );
    const slider = container.querySelector('input[type="range"]') as HTMLInputElement;
    fireEvent.change(slider, { target: { value: '3' } });
    expect(screen.getByText(ru['steps.terminalBadge'])).toBeTruthy();
    expect(container.querySelector('[data-stat="production"]')?.textContent).toBe('—');
    expect(container.querySelector('[data-stat="injection"]')?.textContent).toBe('—');
    expect(container.querySelector('[data-stat="compensation"]')?.textContent).toBe(
      '—'
    );
    const cells = [...rowFor(container, '11').querySelectorAll('td')];
    expect(cells[cells.length - 2]?.textContent).toBe('—');
  });

  it('labels a not commissioned well without showing it as shut', async () => {
    mockFetchWith(fixture);
    const { container } = render(withProviders(<Timeline />));
    await waitFor(() =>
      expect(container.querySelectorAll('tbody tr')).toHaveLength(3)
    );
    const row = rowFor(container, '14');
    expect(row.textContent).toContain(ru['steps.availability.NOT_COMMISSIONED']);
    expect(row.textContent).not.toContain(ru['steps.status.SHUT']);
  });

  it('labels a not commissioned well in english after toggle', async () => {
    localStorage.setItem('aios-lang', 'en');
    mockFetchWith(fixture);
    const { container } = render(withProviders(<Timeline />));
    await waitFor(() =>
      expect(container.querySelectorAll('tbody tr')).toHaveLength(3)
    );
    const row = rowFor(container, '14');
    expect(row.textContent).toContain(en['steps.availability.NOT_COMMISSIONED']);
    expect(row.textContent).not.toContain(en['steps.status.SHUT']);
  });

  it('shows a dictionary error message when fetch fails', async () => {
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new Error('network')));
    render(withProviders(<Timeline />));
    await screen.findByText(ru['steps.error']);
  });
});
