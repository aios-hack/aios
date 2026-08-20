import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { ReactNode } from 'react';
import type { WellsFile } from '../../api/types';
import { dictionaries } from '../../i18n/dictionaries';
import { I18nProvider } from '../../i18n/I18nContext';
import { TimelineProvider } from '../../state/TimelineContext';
import { FieldMap } from './FieldMap';

const { ru, en } = dictionaries;

const fixture: WellsFile = {
  grid: { ni: 10, nj: 12, nk: 6 },
  layers: [
    { id: 1, k_min: 1, k_max: 3 },
    { id: 2, k_min: 5, k_max: 6 }
  ],
  wells: [
    { id: 'W1', i: 2, j: 3, completions: [[1, 2]], layers: [1] },
    { id: 'W2', i: 5, j: 7, completions: [[5, 6]], layers: [2] },
    { id: 'W3', i: 8, j: 4, completions: [[1, 2], [5, 6]], layers: [1, 2] }
  ]
};

const withProviders = (node: ReactNode) => (
  <I18nProvider>
    <TimelineProvider>{node}</TimelineProvider>
  </I18nProvider>
);

const mockFetchWith = (payload: WellsFile) => {
  vi.stubGlobal(
    'fetch',
    vi.fn().mockResolvedValue({ ok: true, json: () => Promise.resolve(payload) })
  );
};

beforeEach(() => {
  localStorage.clear();
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe('FieldMap', () => {
  it('renders a point per well from the fixture', async () => {
    mockFetchWith(fixture);
    const { container } = render(withProviders(<FieldMap />));
    await waitFor(() => expect(container.querySelectorAll('[data-well-id]')).toHaveLength(3));
    const ids = [...container.querySelectorAll('[data-well-id]')].map((c) => c.getAttribute('data-well-id'));
    expect(ids.sort()).toEqual(['W1', 'W2', 'W3']);
  });

  it('dims wells outside the selected layer and updates the counter', async () => {
    mockFetchWith(fixture);
    const { container } = render(withProviders(<FieldMap />));
    await screen.findByText(ru['map.layer.1']);
    fireEvent.click(screen.getByText(ru['map.layer.1']));
    const active = container.querySelectorAll('[data-well-id][data-active="true"]');
    const dimmed = container.querySelectorAll('[data-well-id][data-active="false"]');
    expect(active).toHaveLength(2);
    expect(dimmed).toHaveLength(1);
    const counter = ru['map.shown'].replace('{shown}', '2').replace('{total}', '3');
    expect(screen.getByRole('status', { name: counter })).toBeTruthy();
    fireEvent.click(screen.getByText(ru['map.layer.2']));
    expect(container.querySelectorAll('[data-well-id][data-active="true"]')).toHaveLength(2);
    fireEvent.click(screen.getByText(ru['map.layer.all']));
    expect(container.querySelectorAll('[data-well-id][data-active="true"]')).toHaveLength(3);
  });

  it('shows loading then dictionary labels in russian by default', async () => {
    mockFetchWith(fixture);
    render(withProviders(<FieldMap />));
    expect(screen.getByText(ru['map.loading'])).toBeTruthy();
    await screen.findByText(ru['map.layer.all']);
    expect(screen.getByText(ru['map.legend.both'])).toBeTruthy();
    expect(screen.queryByText(en['map.layer.all'])).toBeNull();
  });

  it('lists only layer categories present on the map', async () => {
    mockFetchWith(fixture);
    render(withProviders(<FieldMap />));
    await screen.findByText(ru['map.legend.layer1']);
    expect(screen.getByText(ru['map.legend.layer2'])).toBeTruthy();
    expect(screen.getByText(ru['map.legend.both'])).toBeTruthy();
    expect(screen.queryByText(ru['map.legend.dim'])).toBeNull();
  });

  it('drops an absent layer category from the legend', async () => {
    mockFetchWith({
      ...fixture,
      wells: fixture.wells.filter((well) => !well.layers.includes(2))
    });
    render(withProviders(<FieldMap />));
    await screen.findByText(ru['map.legend.layer1']);
    expect(screen.queryByText(ru['map.legend.layer2'])).toBeNull();
    expect(screen.queryByText(ru['map.legend.both'])).toBeNull();
  });

  it('adds the dimmed category to the legend once a layer is filtered', async () => {
    mockFetchWith(fixture);
    render(withProviders(<FieldMap />));
    await screen.findByText(ru['map.layer.1']);
    expect(screen.queryByText(ru['map.legend.dim'])).toBeNull();
    fireEvent.click(screen.getByText(ru['map.layer.1']));
    expect(screen.getByText(ru['map.legend.dim'])).toBeTruthy();
  });

  it('shows a dictionary error message when fetch fails', async () => {
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new Error('network')));
    render(withProviders(<FieldMap />));
    await screen.findByText(ru['map.error']);
  });
});
