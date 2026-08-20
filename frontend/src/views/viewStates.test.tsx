import { render, screen } from '@testing-library/react';
import type { ReactNode } from 'react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { dictionaries } from '../i18n/dictionaries';
import { I18nProvider } from '../i18n/I18nContext';
import { ScenarioProvider } from '../state/ScenarioContext';
import { TimelineProvider } from '../state/TimelineContext';
import { FieldMap } from './FieldMap';
import { LambdaGraph } from './LambdaGraph';
import { NpvRank } from './NpvRank';
import { ScenarioLibrary } from './Scenarios/ScenarioLibrary';
import { Timeline } from './Timeline';

const { ru, en } = dictionaries;

const withProviders = (node: ReactNode) => (
  <I18nProvider>
    <ScenarioProvider>
      <TimelineProvider>{node}</TimelineProvider>
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
  { name: 'graph', node: <LambdaGraph />, loading: 'graph.loading', error: 'graph.error' },
  { name: 'map', node: <FieldMap />, loading: 'map.loading', error: 'map.error' },
  { name: 'steps', node: <Timeline />, loading: 'steps.loading', error: 'steps.error' },
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
    render(withProviders(<Timeline />));
    const alert = await screen.findByRole('alert');
    expect(alert.textContent).toContain(en['steps.error']);
    expect(alert.textContent).not.toContain(ru['steps.error']);
  });
});

describe('view empty states', () => {
  it('tells the user the field has no wells rather than drawing an empty plot', async () => {
    serves({ grid: { ni: 10, nj: 12, nk: 6 }, layers: [], wells: [] });
    const { container } = render(withProviders(<FieldMap />));
    await screen.findByText(ru['map.empty']);
    expect(screen.getByText(ru['map.emptyHint'])).toBeTruthy();
    expect(container.querySelector('[data-well-id]')).toBeNull();
  });

  it('tells the user the scenario library is empty rather than showing a bare heading', async () => {
    serves({ submitted: null, scenarios: [] });
    render(withProviders(<ScenarioLibrary />));
    await screen.findByText(ru['scenarios.library.empty']);
    expect(screen.getByText(ru['scenarios.library.emptyHint'])).toBeTruthy();
    expect(screen.queryByRole('button')).toBeNull();
  });
});
