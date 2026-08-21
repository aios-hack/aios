import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { ReactNode } from 'react';
import type {
  ArtifactMeta,
  ScenarioConstraintsSummary,
  ScenarioEntry,
  ScenariosFile,
  TimelineFile
} from '../../api/types';
import { I18nProvider } from '../../i18n/I18nContext';
import { ProvenanceProvider } from '../../state/ProvenanceContext';
import { ScenarioProvider } from '../../state/ScenarioContext';
import { StatusChip } from './StatusChip';

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

const renderChip = async (entries: ScenarioEntry[], meta?: ArtifactMeta): Promise<HTMLElement> => {
  const file: ScenariosFile = { submitted: 'base', scenarios: entries };
  mockFetch(file, meta);
  render(withProviders(<StatusChip />));
  return await screen.findByRole('button');
};

beforeEach(() => {
  localStorage.clear();
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe('StatusChip synthesized verdict', () => {
  it('shows the demo-data warning even when convergence is clean', async () => {
    const button = await renderChip(
      [scenario({ converged: true, self_consistent: true })],
      { kind: 'timeline', provenance: 'synthetic-demo', synthetic: true }
    );
    expect(button.textContent).toContain('Демо-данные');
    expect(button.getAttribute('data-level')).toBe('warn');
  });

  it('shows the confirmed run identifier when final_npv has clean validation', async () => {
    const button = await renderChip([
      scenario({ final_npv: { npv_rub: 1, run_id: 'run-7f3a' }, run_validation_clean: true })
    ]);
    expect(button.textContent).toContain('run-7f3a');
  });

  it('shows an amber unconfirmed state when final_npv lacks a validation flag', async () => {
    const button = await renderChip([
      scenario({ final_npv: { npv_rub: 1, run_id: 'run-7f3a' } })
    ]);
    expect(button.textContent).toContain('число не заявляемо');
  });
});

describe('StatusChip popover accessibility', () => {
  it('opens the full trust board on click, exposes aria-expanded, and closes on Escape returning focus', async () => {
    const button = await renderChip([scenario()]);

    expect(button.getAttribute('aria-expanded')).toBe('false');
    fireEvent.click(button);
    expect(button.getAttribute('aria-expanded')).toBe('true');

    const dialog = await screen.findByRole('dialog');
    expect(dialog.querySelectorAll('.trust-item')).toHaveLength(6);

    fireEvent.keyDown(window, { key: 'Escape' });
    await waitFor(() => expect(screen.queryByRole('dialog')).toBeNull());
    expect(document.activeElement).toBe(button);
  });

  it('does not move focus into the popover when it opens', async () => {
    const button = await renderChip([scenario()]);
    fireEvent.click(button);
    const dialog = await screen.findByRole('dialog');
    expect(dialog.contains(document.activeElement)).toBe(false);
  });
});
