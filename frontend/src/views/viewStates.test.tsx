import { render, screen } from '@testing-library/react';
import type { ReactNode } from 'react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { dictionaries } from '../i18n/dictionaries';
import { useT } from '../i18n/I18nContext';
import { I18nProvider } from '../i18n/I18nContext';
import { PlaybackProvider, usePlayback } from '../state/PlaybackContext';
import { ScenarioProvider } from '../state/ScenarioContext';
import { TimelineProvider, useTimeline } from '../state/TimelineContext';
import { ViewStatus } from '../ui/ViewStatus';
import { FieldProjection } from './FieldProjection';
import { MoneyComparison } from './Money/MoneyComparison';
import { NpvRank } from './NpvRank';
import { ScenarioLibrary } from './Scenarios/ScenarioLibrary';
import { HistoryTable } from './Timeline/HistoryTable';
import { StepControls } from './Timeline/StepControls';
import { WellsTable } from './Timeline/WellsTable';

const { ru, en } = dictionaries;

const StepsTestView = () => {
  const t = useT();
  const { timeline, stepIndex, selectedWell, selectWell } = useTimeline();
  const { playing, selectStep, onStep, togglePlay } = usePlayback();

  if (timeline.status === 'loading') {
    return <ViewStatus kind="loading" title={t('steps.loading')} />;
  }
  if (timeline.status === 'error') {
    return <ViewStatus kind="error" title={t('steps.error')} hint={t('steps.errorHint')} />;
  }

  const steps = timeline.data.steps;
  const current = Math.min(stepIndex, steps.length - 1);
  const step = steps[current];

  return (
    <section>
      <StepControls
        steps={steps}
        stepIndex={current}
        playing={playing}
        onSelect={selectStep}
        onStep={onStep}
        onTogglePlay={togglePlay}
      />
      <WellsTable wells={step.wells} selectedWell={selectedWell} onSelectWell={selectWell} />
    </section>
  );
};

const withProviders = (node: ReactNode) => (
  <I18nProvider>
    <ScenarioProvider>
      <TimelineProvider>
        <PlaybackProvider>{node}</PlaybackProvider>
      </TimelineProvider>
    </ScenarioProvider>
  </I18nProvider>
);

const neverResolves = () => {
  vi.stubGlobal('fetch', vi.fn(() => new Promise(() => {})));
};

const rejects = () => {
  vi.stubGlobal('fetch', vi.fn(() => Promise.reject(new Error('offline'))));
};

const httpError = () => {
  vi.stubGlobal(
    'fetch',
    vi.fn(() => Promise.resolve({ ok: false, status: 500, json: () => Promise.resolve({}) }))
  );
};

const serves = (payload: unknown) => {
  vi.stubGlobal(
    'fetch',
    vi.fn(() => Promise.resolve({ ok: true, json: () => Promise.resolve(payload) }))
  );
};

const views: { name: string; node: ReactNode; loading: string; error: string }[] = [
  {
    name: 'projection',
    node: <FieldProjection />,
    loading: 'projection.loading',
    error: 'projection.error'
  },
  { name: 'steps', node: <StepsTestView />, loading: 'steps.loading', error: 'steps.error' },
  { name: 'npv', node: <NpvRank />, loading: 'npv.loading', error: 'npv.error' },
  {
    name: 'scenarios',
    node: <ScenarioLibrary />,
    loading: 'scenarios.library.loading',
    error: 'scenarios.library.error'
  }
];

beforeEach(() => {
  localStorage.clear();
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe('view loading states', () => {
  for (const view of views) {
    it(`shows a busy status for ${view.name} while data is in flight`, async () => {
      neverResolves();
      render(withProviders(view.node));
      const status = await screen.findByRole('status');
      expect(status.textContent).toContain(ru[view.loading]);
      expect(status.getAttribute('aria-busy')).toBe('true');
    });
  }
});

describe('view error states', () => {
  for (const view of views) {
    it(`shows an alert for ${view.name} when the request is rejected`, async () => {
      rejects();
      render(withProviders(view.node));
      const alert = await screen.findByRole('alert');
      expect(alert.textContent).toContain(ru[view.error]);
    });

    it(`shows an alert for ${view.name} on an http failure`, async () => {
      httpError();
      render(withProviders(view.node));
      const alert = await screen.findByRole('alert');
      expect(alert.textContent).toContain(ru[view.error]);
    });

    it(`shows an alert for ${view.name} when the payload is the wrong shape`, async () => {
      serves({ steps: 'not-an-array', wells: 42, nodes: null, scenarios: 7 });
      render(withProviders(view.node));
      const alert = await screen.findByRole('alert');
      expect(alert.textContent).toContain(ru[view.error]);
    });
  }

  it('translates the error copy when english is active', async () => {
    localStorage.setItem('aios-lang', 'en');
    rejects();
    render(withProviders(<StepsTestView />));
    const alert = await screen.findByRole('alert');
    expect(alert.textContent).toContain(en['steps.error']);
    expect(alert.textContent).not.toContain(ru['steps.error']);
  });
});

describe('view empty states', () => {
  it('tells the user the scenario library is empty rather than showing a bare heading', async () => {
    serves({ submitted: null, scenarios: [] });
    render(withProviders(<ScenarioLibrary />));
    await screen.findByText(ru['scenarios.library.empty']);
    expect(screen.getByText(ru['scenarios.library.emptyHint'])).toBeTruthy();
    expect(screen.queryByRole('button')).toBeNull();
  });

  it('refuses a timeline with no steps rather than presenting an empty schedule', async () => {
    serves(timelineWithout({ steps: [] }));
    render(withProviders(<HistoryTable />));
    const alert = await screen.findByRole('alert');
    expect(alert.textContent).toContain(ru['steps.error']);
    expect(screen.queryByTestId('history-table')).toBeNull();
  });
});

describe('money comparison reports a failed scenario index', () => {
  it('shows a busy status while the index is in flight', async () => {
    neverResolves();
    render(withProviders(<MoneyComparison />));
    const statuses = await screen.findAllByRole('status');
    expect(statuses.some((node) => node.textContent?.includes(ru['scenarios.compare.loading']))).toBe(
      true
    );
  });

  it('shows an alert instead of silently rendering an empty panel', async () => {
    rejects();
    render(withProviders(<MoneyComparison />));
    const alerts = await screen.findAllByRole('alert');
    expect(alerts.some((node) => node.textContent?.includes(ru['scenarios.compare.error']))).toBe(
      true
    );
  });

  it('shows an alert when the index payload is the wrong shape', async () => {
    serves({ scenarios: 7 });
    render(withProviders(<MoneyComparison />));
    const alerts = await screen.findAllByRole('alert');
    expect(alerts.some((node) => node.textContent?.includes(ru['scenarios.compare.error']))).toBe(
      true
    );
  });
});

const timelineWithout = (missing: Record<string, unknown>): unknown => ({
  model: 'Model_Z',
  t0: '2007-01-01',
  n_control_dates: 1,
  n_intervals: 0,
  wells: ['W1'],
  meta: { kind: 'timeline', provenance: 'model-z-base-run' },
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
      wells: [
        {
          well: 'W1',
          availability: 'AVAILABLE',
          role: 'PROD',
          operating_status: 'OPEN',
          setpoint: 1,
          liquid_rate: 1,
          injection_rate: 0,
          bhp: 1,
          watercut: 0.5,
          fact_to_target: 1,
          cumulative_liquid: 1
        }
      ]
    }
  ],
  ...missing
});

describe('view error states for payloads a consumer would dereference', () => {
  it('refuses a timeline without the well column list rather than crashing the table', async () => {
    serves(timelineWithout({ wells: undefined }));
    render(withProviders(<StepsTestView />));
    const alert = await screen.findByRole('alert');
    expect(alert.textContent).toContain(ru['steps.error']);
  });

  it('refuses a timeline whose provenance is not text the notice can read', async () => {
    serves(timelineWithout({ meta: { kind: 'timeline', provenance: 42 } }));
    render(withProviders(<StepsTestView />));
    const alert = await screen.findByRole('alert');
    expect(alert.textContent).toContain(ru['steps.error']);
  });

  it('accepts the same timeline once the column list is present', async () => {
    serves(timelineWithout({}));
    render(withProviders(<StepsTestView />));
    await screen.findByText('W1');
    expect(screen.queryByRole('alert')).toBeNull();
  });

  it('refuses a scenario index whose entries lack the flags the library branches on', async () => {
    serves({
      submitted: 'final',
      scenarios: [
        {
          id: 'final',
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
        }
      ]
    });
    render(withProviders(<ScenarioLibrary />));
    const alert = await screen.findByRole('alert');
    expect(alert.textContent).toContain(ru['scenarios.library.error']);
  });
});
