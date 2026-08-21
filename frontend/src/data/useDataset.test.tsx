import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import type { ReactNode } from 'react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { GraphFile, NpvFile, ScenariosFile, WellsFile } from '../api/types';
import { dictionaries } from '../i18n/dictionaries';
import { I18nProvider } from '../i18n/I18nContext';
import { ScenarioProvider } from '../state/ScenarioContext';
import { TimelineProvider } from '../state/TimelineContext';
import { FieldProjection } from '../views/FieldProjection';
import { NpvRank } from '../views/NpvRank';
import { ScenarioLibrary } from '../views/Scenarios/ScenarioLibrary';

const graphFixture = (id: string): GraphFile => ({
  window: { start: '2007-01-01', end: '2008-07-01' },
  nodes: [
    { id: `${id}-I1`, role: 'INJ', group: 'G1', x: 10, y: 10 },
    { id: `${id}-P1`, role: 'PROD', group: 'G1', x: 20, y: 14 }
  ],
  edges: [{ injector: `${id}-I1`, producer: `${id}-P1`, weight: 0.9 }],
  groups: [{ id: 'G1', wells: [`${id}-I1`, `${id}-P1`] }],
  weight_range: { min: 0.9, max: 0.9 },
  meta: { lag_months: 3, amplitude: 0.2, stability: 0.77, rank: 2, condition_number: 4.25 },
  layout: { size: 100, seed: 20070101 }
});

const wellsFixture: WellsFile = {
  grid: { ni: 10, nj: 12, nk: 6 },
  layers: [{ id: 1, k_min: 1, k_max: 3 }],
  wells: [{ id: 'W1', i: 2, j: 3, completions: [[1, 2]], layers: [1] }]
};

const npvFixture: NpvFile = {
  wells: [{ well: '10', pre_tax: 50, with_allocated_tax: 40 }],
  total: { pre_tax: 50, with_allocated_tax: 40 },
  npv_methodology: 40
};

const scenariosFixture: ScenariosFile = {
  submitted: 'final',
  scenarios: ['final', 'what_if'].map((id) => ({
    id,
    config_hash: 'a'.repeat(64),
    converged: true,
    self_consistent: true,
    is_submitted: id === 'final',
    npv_methodology: 1,
    constraints: {
      injection_limits: 0,
      liquid_limits: 0,
      production_floors: 0,
      watercut_limits: 0,
      well_outages: 0,
      infrastructure: 0,
      years: [],
      outage_wells: [],
      empty: true
    }
  }))
};

const { ru } = dictionaries;

const requested: string[] = [];

const scenarioOf = (url: string): string =>
  url.includes('/data/what_if/') ? 'what_if' : 'base';

const mockFetch = () => {
  requested.length = 0;
  vi.stubGlobal(
    'fetch',
    vi.fn((url: string) => {
      requested.push(url);
      const payload = url.includes('scenarios.json')
        ? scenariosFixture
        : url.includes('graph.json')
          ? graphFixture(scenarioOf(url))
          : url.includes('wells.json')
            ? wellsFixture
            : url.includes('npv.json')
              ? npvFixture
              : {};
      return Promise.resolve({ ok: true, json: () => Promise.resolve(payload) });
    })
  );
};

const withProviders = (node: ReactNode) => (
  <I18nProvider>
    <ScenarioProvider>
      <TimelineProvider>{node}</TimelineProvider>
    </ScenarioProvider>
  </I18nProvider>
);

const urlsFor = (file: string): string[] => requested.filter((url) => url.includes(file));

const switchToWhatIf = (container: HTMLElement) =>
  fireEvent.click(container.querySelector('[data-scenario-id="what_if"]') as HTMLElement);

beforeEach(() => {
  localStorage.clear();
  mockFetch();
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe('scenario-scoped datasets', () => {
  it('refetches the graph from the active scenario path and redraws its nodes', async () => {
    const { container } = render(
      withProviders(
        <>
          <ScenarioLibrary />
          <FieldProjection />
        </>
      )
    );
    await screen.findByTestId('field-projection-plot');
    expect(urlsFor('graph.json')).toEqual(['/data/graph.json']);
    expect(container.querySelector('[data-well-id="base-I1"]')).not.toBeNull();

    switchToWhatIf(container);

    await waitFor(() =>
      expect(urlsFor('graph.json')).toContain('/data/what_if/graph.json')
    );
    await waitFor(() =>
      expect(container.querySelector('[data-well-id="what_if-I1"]')).not.toBeNull()
    );
    expect(container.querySelector('[data-well-id="base-I1"]')).toBeNull();
  });

  it('refetches the npv table per scenario but keeps well geometry global', async () => {
    const { container } = render(
      withProviders(
        <>
          <ScenarioLibrary />
          <FieldProjection />
          <NpvRank />
        </>
      )
    );
    await waitFor(() => expect(urlsFor('wells.json')).toEqual(['/data/wells.json']));
    expect(urlsFor('npv.json')).toEqual(['/data/npv.json']);

    switchToWhatIf(container);

    await waitFor(() => expect(urlsFor('npv.json')).toContain('/data/what_if/npv.json'));
    expect(urlsFor('wells.json')).toEqual(['/data/wells.json']);
  });

  it('keeps the scenario index global so the library survives a switch', async () => {
    const { container } = render(withProviders(<ScenarioLibrary />));
    await screen.findByText('what_if');

    switchToWhatIf(container);

    await waitFor(() =>
      expect(container.querySelector('[data-active="true"]')?.getAttribute('data-scenario-id')).toBe(
        'what_if'
      )
    );
    expect(urlsFor('scenarios.json')).toEqual(['/data/scenarios.json']);
    expect(screen.getByText('final')).toBeTruthy();
  });

  it('rejects a wells payload that does not match the schema', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(() => Promise.resolve({ ok: true, json: () => Promise.resolve({ wells: 'nope' }) }))
    );
    render(withProviders(<FieldProjection />));
    await screen.findByText(ru['projection.error']);
  });
});
