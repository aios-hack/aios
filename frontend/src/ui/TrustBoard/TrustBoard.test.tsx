import { render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { ReactNode } from 'react';
import type {
  ArtifactMeta,
  ScenarioConstraintsSummary,
  ScenarioEntry,
  ScenariosFile,
  TimelineFile
} from '../../api/types';
import { dictionaries } from '../../i18n/dictionaries';
import { I18nProvider } from '../../i18n/I18nContext';
import { ProvenanceProvider } from '../../state/ProvenanceContext';
import { ScenarioProvider } from '../../state/ScenarioContext';
import { TrustBoard } from './TrustBoard';

const { ru } = dictionaries;

const summary = (): ScenarioConstraintsSummary => ({
  injection_limits: 0,
  liquid_limits: 0,
  production_floors: 0,
  watercut_limits: 0,
  well_outages: 0,
  infrastructure: 0,
  years: [],
  outage_wells: [],
  empty: true
});

const scenario = (overrides: Partial<ScenarioEntry> = {}): ScenarioEntry => ({
  id: 'base',
  config_hash: 'a'.repeat(64),
  converged: true,
  self_consistent: true,
  is_submitted: true,
  npv_methodology: null,
  constraints: summary(),
  ...overrides
});

const step = {
  control_step: 0,
  date: '2007-01-01',
  terminal: false,
  field: { production: 1, injection: 1, compensation: 1, npv_cumulative: 1, active_wells: 1 },
  wells: []
};

const timelineFixture = (meta?: ArtifactMeta): TimelineFile => ({
  meta,
  model: 'Model_Z',
  t0: '2007-01-01',
  n_control_dates: 2,
  n_intervals: 1,
  wells: ['10'],
  steps: [step]
});

const mockFetch = (index: unknown, meta?: ArtifactMeta) => {
  vi.stubGlobal(
    'fetch',
    vi.fn((url: string) =>
      Promise.resolve({
        ok: true,
        json: () =>
          Promise.resolve(url.includes('scenarios.json') ? index : timelineFixture(meta))
      })
    )
  );
};

const withProviders = (node: ReactNode) => (
  <I18nProvider>
    <ScenarioProvider>
      <ProvenanceProvider>{node}</ProvenanceProvider>
    </ScenarioProvider>
  </I18nProvider>
);

const renderBoard = async (
  entries: ScenarioEntry[],
  meta?: ArtifactMeta
): Promise<HTMLElement> => {
  const file: ScenariosFile = { submitted: 'base', scenarios: entries };
  mockFetch(file, meta);
  render(withProviders(<TrustBoard />));
  return await screen.findByTestId('trust-board');
};

const item = (board: HTMLElement, id: string): HTMLElement =>
  board.querySelector(`[data-indicator="${id}"]`) as HTMLElement;

beforeEach(() => {
  localStorage.clear();
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe('TrustBoard number indicator', () => {
  it('reports a surrogate forecast when final_npv is null', async () => {
    const board = await renderBoard([scenario({ final_npv: null })]);
    const number = item(board, 'number');

    expect(number.textContent).toContain(ru['trust.number.forecast']);
    expect(number.getAttribute('data-status')).toBe('unmeasured');
    expect(number.textContent).not.toContain(ru['trust.number.confirmed']);
  });

  it('reports a surrogate forecast when final_npv is absent entirely', async () => {
    const board = await renderBoard([scenario()]);
    expect(item(board, 'number').textContent).toContain(ru['trust.number.forecast']);
  });

  it('reports a confirmed computation with its run identifier when final_npv is filled', async () => {
    const board = await renderBoard([
      scenario({ final_npv: { npv_rub: 10786000000, run_id: 'run-7f3a' } })
    ]);
    const number = item(board, 'number');

    expect(number.textContent).toContain('run-7f3a');
    expect(number.textContent).toContain(
      ru['trust.number.confirmed'].replace('{run}', 'run-7f3a')
    );
    expect(number.getAttribute('data-status')).toBe('neutral');
    expect(number.textContent).not.toContain(ru['trust.number.forecast']);
  });
});

describe('TrustBoard missing measurements', () => {
  it('says "not measured" instead of zero for an absent ood score', async () => {
    const board = await renderBoard([scenario({ ood_score: null, ood_threshold: null })]);
    const domain = item(board, 'domain');

    expect(domain.textContent).toContain(ru['trust.unmeasured']);
    expect(domain.getAttribute('data-status')).toBe('unmeasured');
    expect(domain.textContent).not.toContain('0');
    expect(domain.textContent).not.toContain(ru['trust.domain.inside']);
  });

  it('says "not measured" instead of zero for an absent worst regret', async () => {
    const board = await renderBoard([scenario({ worst_regret: null })]);
    const regret = item(board, 'regret');

    expect(regret.textContent).toContain(ru['trust.unmeasured']);
    expect(regret.getAttribute('data-status')).toBe('unmeasured');
    expect(regret.textContent).not.toContain('0');
  });

  it('separates a measured good domain from an unmeasured one by status', async () => {
    const measured = await renderBoard([scenario({ ood_score: 0.18, ood_threshold: 0.5 })]);
    const domain = item(measured, 'domain');

    expect(domain.textContent).toContain(ru['trust.domain.inside']);
    expect(domain.getAttribute('data-status')).toBe('neutral');
    expect(domain.textContent).not.toContain(ru['trust.unmeasured']);
  });
});

describe('TrustBoard indicator statuses', () => {
  it('marks the scenario as out of domain when the score exceeds the threshold', async () => {
    const board = await renderBoard([scenario({ ood_score: 0.82, ood_threshold: 0.5 })]);
    const domain = item(board, 'domain');

    expect(domain.textContent).toContain(ru['trust.domain.outside']);
    expect(domain.getAttribute('data-status')).toBe('danger');
  });

  it('names the worst regret scenario and its battery part', async () => {
    const board = await renderBoard([
      scenario({
        worst_regret: {
          scenario_id: 'holdout-outage-and-injection-cap',
          value_rub: 201000000,
          part: 'holdout'
        }
      })
    ]);
    const regret = item(board, 'regret');

    expect(regret.textContent).toContain('holdout-outage-and-injection-cap');
    expect(regret.textContent).toContain(ru['trust.regret.part.holdout']);
    expect(regret.textContent).not.toContain(ru['trust.unmeasured']);
  });

  it('flags a fixed point that did not converge as danger', async () => {
    const board = await renderBoard([scenario({ converged: false })]);
    const converged = item(board, 'converged');

    expect(converged.textContent).toContain(ru['trust.converged.no']);
    expect(converged.getAttribute('data-status')).toBe('danger');
  });

  it('carries the synthetic banner as the provenance indicator', async () => {
    const board = await renderBoard([scenario()], {
      kind: 'timeline',
      provenance: 'synthetic-demo',
      synthetic: true
    });
    const provenance = item(board, 'provenance');

    expect(provenance.querySelector('.synthetic-mark')).not.toBeNull();
    expect(provenance.getAttribute('data-status')).toBe('danger');
  });

  it('states that provenance is unknown when the bundle carries no meta', async () => {
    const board = await renderBoard([scenario()]);
    const provenance = item(board, 'provenance');

    expect(provenance.textContent).toContain(ru['trust.provenance.unknown']);
    expect(provenance.getAttribute('data-status')).toBe('unmeasured');
  });

  it('renders exactly six indicators', async () => {
    const board = await renderBoard([scenario()]);
    expect(board.querySelectorAll('.trust-item')).toHaveLength(6);
  });
});

describe('TrustBoard without a usable index', () => {
  it('says the index is unavailable instead of inventing flags', async () => {
    mockFetch({ scenarios: 'broken' });
    render(withProviders(<TrustBoard />));

    await waitFor(() =>
      expect(screen.getByTestId('trust-board-notice').textContent).toBe(
        ru['trust.index.error']
      )
    );
    expect(screen.queryByTestId('trust-board')).toBeNull();
  });

  it('says the active scenario is missing when the index does not list it', async () => {
    mockFetch({ submitted: null, scenarios: [] });
    render(withProviders(<TrustBoard />));

    await waitFor(() =>
      expect(screen.getByTestId('trust-board-notice').textContent).toBe(
        ru['trust.index.missing']
      )
    );
  });
});
