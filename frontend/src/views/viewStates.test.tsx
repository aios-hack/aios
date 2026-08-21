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
import { NpvRank } from './NpvRank';
import { ScenarioLibrary } from './Scenarios/ScenarioLibrary';
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
});
