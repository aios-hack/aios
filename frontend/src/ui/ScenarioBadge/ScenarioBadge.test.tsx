import { render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { ReactNode } from 'react';
import type { ScenariosFile } from '../../api/types';
import { dictionaries } from '../../i18n/dictionaries';
import { I18nProvider } from '../../i18n/I18nContext';
import { ScenarioProvider } from '../../state/ScenarioContext';
import { ScenarioBadge } from './ScenarioBadge';

const { ru } = dictionaries;

const constraints = {
  injection_limits: 1,
  liquid_limits: 1,
  production_floors: 1,
  watercut_limits: 1,
  well_outages: 0,
  outage_wells: [],
  infrastructure: 0,
  years: [2007],
  empty: false
};

const scenariosFixture: ScenariosFile = {
  submitted: 'base',
  scenarios: [
    {
      id: 'base',
      config_hash: 'a'.repeat(64),
      converged: true,
      self_consistent: true,
      is_submitted: true,
      npv_methodology: 141177,
      constraints
    },
    {
      id: 'whatif-injection-cut',
      config_hash: 'b'.repeat(64),
      converged: true,
      self_consistent: true,
      is_submitted: false,
      npv_methodology: null,
      constraints
    }
  ]
};

const withProviders = (node: ReactNode) => (
  <I18nProvider>
    <ScenarioProvider>{node}</ScenarioProvider>
  </I18nProvider>
);

const mockScenarios = (payload: ScenariosFile = scenariosFixture) => {
  vi.stubGlobal(
    'fetch',
    vi.fn(() => Promise.resolve({ ok: true, json: () => Promise.resolve(payload) }))
  );
};

beforeEach(() => {
  localStorage.clear();
  mockScenarios();
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe('the header names the scenario in one control, not four', () => {
  it('shows the scenario id and nothing else as visible text', async () => {
    const { container } = render(withProviders(<ScenarioBadge onOpenLibrary={() => undefined} />));
    const badge = await waitFor(() => {
      const node = container.querySelector('.scenario-badge');
      expect(node).not.toBeNull();
      return node as HTMLElement;
    });

    expect(badge.textContent).toBe('base');
  });

  it('drops the label, the kind pill and the hint that used to crowd it', async () => {
    const { container } = render(withProviders(<ScenarioBadge onOpenLibrary={() => undefined} />));
    await waitFor(() => expect(container.querySelector('.scenario-badge')).not.toBeNull());

    expect(screen.queryByText(ru['scenarios.badge.submitted'])).toBeNull();
    expect(container.querySelector('.scenario-badge-kind')).toBeNull();
    expect(container.querySelector('.info-hint')).toBeNull();
  });

  it('still tells assistive tech what the scenario is and where the control leads', async () => {
    const { container } = render(withProviders(<ScenarioBadge onOpenLibrary={() => undefined} />));
    const badge = await waitFor(() => {
      const node = container.querySelector('.scenario-badge');
      expect(node).not.toBeNull();
      return node as HTMLElement;
    });

    const label = badge.getAttribute('aria-label') ?? '';
    expect(label).toContain('base');
    expect(label).toContain(ru['scenarios.badge.submitted']);
  });

  it('carries the submitted state as data, so colour is not the only signal', async () => {
    const { container } = render(withProviders(<ScenarioBadge onOpenLibrary={() => undefined} />));
    const badge = await waitFor(() => {
      const node = container.querySelector('.scenario-badge');
      expect(node).not.toBeNull();
      return node as HTMLElement;
    });

    expect(badge.getAttribute('data-submitted')).toBe('true');
  });

  it('opens the library instead of a panel that duplicates it', async () => {
    const onOpenLibrary = vi.fn();
    const { container } = render(withProviders(<ScenarioBadge onOpenLibrary={onOpenLibrary} />));
    const badge = await waitFor(() => {
      const node = container.querySelector('.scenario-badge');
      expect(node).not.toBeNull();
      return node as HTMLElement;
    });

    expect(badge.tagName).toBe('BUTTON');
    badge.click();
    expect(onOpenLibrary).toHaveBeenCalledTimes(1);
  });

  it('stays inert text when no destination was given', async () => {
    const { container } = render(withProviders(<ScenarioBadge />));
    const badge = await waitFor(() => {
      const node = container.querySelector('.scenario-badge');
      expect(node).not.toBeNull();
      return node as HTMLElement;
    });

    expect(badge.tagName).toBe('P');
  });

  it('says nothing at all when there is only one scenario to be in', async () => {
    mockScenarios({
      submitted: 'base',
      scenarios: [scenariosFixture.scenarios[0]]
    });
    const { container } = render(withProviders(<ScenarioBadge onOpenLibrary={() => undefined} />));

    await new Promise((resolve) => setTimeout(resolve, 0));
    expect(container.querySelector('.scenario-badge')).toBeNull();
  });
});
