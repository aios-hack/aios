import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import type { ReactNode } from 'react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { ScenariosFile, TimelineFile, TimelineWellRow } from '../api/types';
import { dictionaries } from '../i18n/dictionaries';
import { I18nProvider } from '../i18n/I18nContext';
import { ScenarioProvider } from '../state/ScenarioContext';
import { TimelineProvider } from '../state/TimelineContext';
import { ScenarioLibrary } from '../views/Scenarios/ScenarioLibrary';
import { Timeline } from '../views/Timeline';
import { WellCard } from '../views/WellCard';

const { ru } = dictionaries;

const row = (well: string): TimelineWellRow => ({
  well,
  availability: 'AVAILABLE',
  role: 'PROD',
  operating_status: 'OPEN',
  setpoint: 50,
  liquid_rate: 70,
  injection_rate: 0,
  bhp: 91,
  watercut: 0.5,
  fact_to_target: 1.4,
  cumulative_liquid: 2100
});

const timelineFor = (wells: string[], steps: number): TimelineFile => ({
  model: 'Model_Z',
  t0: '2007-01-01',
  n_control_dates: steps,
  n_intervals: steps - 1,
  wells,
  steps: Array.from({ length: steps }, (_, k) => ({
    control_step: k,
    date: `2007-0${k + 1}-01`,
    terminal: k === steps - 1,
    field: {
      production: 2000 + k,
      injection: 1500 + k,
      compensation: 0.75,
      npv_cumulative: 1000 * (k + 1),
      active_wells: wells.length
    },
    wells: wells.map(row)
  }))
});

const baseTimeline = timelineFor(['10', '11', '12'], 4);
const whatIfTimeline = timelineFor(['10'], 2);

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

const mockFetch = () => {
  vi.stubGlobal(
    'fetch',
    vi.fn((url: string) => {
      const payload = url.includes('scenarios.json')
        ? scenariosFixture
        : url.includes('timeline.json')
          ? url.includes('/what_if/')
            ? whatIfTimeline
            : baseTimeline
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

const switchToWhatIf = (container: HTMLElement) =>
  fireEvent.click(container.querySelector('[data-scenario-id="what_if"]') as HTMLElement);

const rows = (container: HTMLElement): string[] =>
  [...container.querySelectorAll('tbody tr')].map(
    (node) => node.getAttribute('data-well-id') ?? ''
  );

beforeEach(() => {
  localStorage.clear();
  mockFetch();
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe('switching scenario', () => {
  it('reloads the well table from the new scenario', async () => {
    const { container } = render(
      withProviders(
        <>
          <ScenarioLibrary />
          <Timeline />
        </>
      )
    );
    await waitFor(() => expect(rows(container)).toEqual(['10', '11', '12']));

    switchToWhatIf(container);

    await waitFor(() => expect(rows(container)).toEqual(['10']));
  });

  it('closes the card for a well the new scenario does not contain', async () => {
    const { container } = render(
      withProviders(
        <>
          <ScenarioLibrary />
          <Timeline />
          <WellCard />
        </>
      )
    );
    await waitFor(() => expect(rows(container)).toEqual(['10', '11', '12']));
    fireEvent.click(container.querySelector('tr[data-well-id="12"]') as HTMLElement);
    await screen.findByText(ru['wellcard.title'].replace('{well}', '12'));

    switchToWhatIf(container);

    await waitFor(() =>
      expect(screen.queryByText(ru['wellcard.title'].replace('{well}', '12'))).toBeNull()
    );
    expect(screen.queryByRole('dialog')).toBeNull();
  });

  it('rewinds the step slider so it never points past the shorter scenario', async () => {
    const { container } = render(
      withProviders(
        <>
          <ScenarioLibrary />
          <Timeline />
        </>
      )
    );
    await waitFor(() => expect(rows(container)).toEqual(['10', '11', '12']));
    const slider = () => container.querySelector('input[type="range"]') as HTMLInputElement;
    fireEvent.change(slider(), { target: { value: '3' } });
    expect(slider().value).toBe('3');

    switchToWhatIf(container);

    await waitFor(() => expect(rows(container)).toEqual(['10']));
    expect(slider().max).toBe('1');
    expect(Number(slider().value)).toBeLessThanOrEqual(1);
  });

  it('surfaces the error state when the new scenario has no timeline file', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn((url: string) => {
        if (url.includes('scenarios.json')) {
          return Promise.resolve({ ok: true, json: () => Promise.resolve(scenariosFixture) });
        }
        if (url.includes('/what_if/')) {
          return Promise.resolve({ ok: false, status: 404, json: () => Promise.resolve({}) });
        }
        return Promise.resolve({ ok: true, json: () => Promise.resolve(baseTimeline) });
      })
    );
    const { container } = render(
      withProviders(
        <>
          <ScenarioLibrary />
          <Timeline />
        </>
      )
    );
    await waitFor(() => expect(rows(container)).toEqual(['10', '11', '12']));

    switchToWhatIf(container);

    const alert = await screen.findByRole('alert');
    expect(alert.textContent).toContain(ru['steps.error']);
  });
});
