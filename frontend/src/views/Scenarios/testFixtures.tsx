import { act } from '@testing-library/react';
import { vi } from 'vitest';
import type { ReactNode } from 'react';
import type { ScenarioConstraintsSummary, ScenariosFile, TimelineFile } from '../../api/types';
import { I18nProvider } from '../../i18n/I18nContext';
import { ScenarioProvider } from '../../state/ScenarioContext';
import { TimelineProvider } from '../../state/TimelineContext';

export const summary = (
  overrides: Partial<ScenarioConstraintsSummary> = {}
): ScenarioConstraintsSummary => ({
  injection_limits: 1,
  liquid_limits: 0,
  production_floors: 0,
  watercut_limits: 0,
  well_outages: 0,
  infrastructure: 0,
  years: [2007],
  outage_wells: [],
  empty: false,
  ...overrides
});

export const scenariosFixture: ScenariosFile = {
  submitted: 'final',
  scenarios: [
    {
      id: 'final',
      config_hash: 'a'.repeat(64),
      converged: true,
      self_consistent: true,
      is_submitted: true,
      npv_methodology: 123456789,
      constraints: summary()
    },
    {
      id: 'what_if',
      config_hash: 'b'.repeat(64),
      converged: false,
      self_consistent: true,
      is_submitted: false,
      npv_methodology: null,
      constraints: summary({ injection_limits: 0, years: [], empty: true })
    }
  ]
};

export const timelineFixture = (id: string): TimelineFile => ({
  model: `Model_${id}`,
  t0: '2007-01-01',
  n_control_dates: 4,
  n_intervals: 3,
  wells: ['10'],
  steps: [
    {
      control_step: 0,
      date: '2007-01-01',
      terminal: false,
      field: {
        production: 1,
        injection: 1,
        compensation: 1,
        npv_cumulative: 1,
        active_wells: 1
      },
      wells: []
    }
  ]
});

export const requested: string[] = [];

export const mockFetch = () => {
  requested.length = 0;
  vi.stubGlobal(
    'fetch',
    vi.fn((url: string) => {
      requested.push(url);
      if (url.includes('scenarios.json')) {
        return Promise.resolve({ ok: true, json: () => Promise.resolve(scenariosFixture) });
      }
      if (url.includes('timeline.json')) {
        const id = url.includes('/data/what_if/') ? 'what_if' : 'base';
        return Promise.resolve({ ok: true, json: () => Promise.resolve(timelineFixture(id)) });
      }
      return Promise.resolve({ ok: true, json: () => Promise.resolve({}) });
    })
  );
};

export const withProviders = (node: ReactNode) => (
  <I18nProvider>
    <ScenarioProvider>
      <TimelineProvider>{node}</TimelineProvider>
    </ScenarioProvider>
  </I18nProvider>
);

export const flushProviders = async () => {
  await act(async () => {
    await Promise.resolve();
  });
};
