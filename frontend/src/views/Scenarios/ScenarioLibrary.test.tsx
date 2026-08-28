import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { dictionaries } from '../../i18n/dictionaries';
import { ScenarioLibrary } from './ScenarioLibrary';
import { mockFetch, requested, withProviders } from './testFixtures';

const { ru } = dictionaries;

const renderLibrary = async () => {
  const view = render(withProviders(<ScenarioLibrary />));
  await waitFor(() => expect(screen.getByText('final')).toBeTruthy());
  return view;
};

beforeEach(() => {
  localStorage.clear();
  mockFetch();
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe('ScenarioLibrary', () => {
  it('marks the submitted scenario with a badge and shows its NPV', async () => {
    const { container } = await renderLibrary();
    const submitted = container.querySelector('[data-scenario-id="final"]') as HTMLElement;
    const whatIf = container.querySelector('[data-scenario-id="what_if"]') as HTMLElement;

    expect(submitted.getAttribute('data-submitted')).toBe('true');
    expect(within(submitted).getByText(ru['scenarios.badge.submitted'])).toBeTruthy();
    expect(submitted.textContent).toContain('123');
    expect(whatIf.getAttribute('data-submitted')).toBe('false');
    expect(within(whatIf).getByText(ru['scenarios.badge.whatIf'])).toBeTruthy();
  });

  it('shows convergence flags from the index without inventing numbers', async () => {
    const { container } = await renderLibrary();
    const whatIf = container.querySelector('[data-scenario-id="what_if"]') as HTMLElement;
    expect(within(whatIf).getByText(ru['scenarios.flag.notConverged'])).toBeTruthy();
    expect(whatIf.textContent).toContain(ru['scenarios.library.noConstraints']);
    expect(whatIf.textContent).not.toContain('₽');
  });

  it('switches the active scenario and refetches view data from its path', async () => {
    const { container } = await renderLibrary();
    expect(requested).toContain('/data/timeline.json');

    fireEvent.click(container.querySelector('[data-scenario-id="what_if"]') as HTMLElement);

    await waitFor(() => expect(requested).toContain('/data/what_if/timeline.json'));
    const active = container.querySelector('[data-active="true"]') as HTMLElement;
    expect(active.getAttribute('data-scenario-id')).toBe('what_if');
    expect(active.getAttribute('aria-pressed')).toBe('true');
  });

  it('reports a missing index instead of rendering made-up scenarios', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn((url: string) =>
        url.includes('scenarios.json')
          ? Promise.resolve({ ok: false, status: 404, json: () => Promise.resolve({}) })
          : Promise.resolve({ ok: true, json: () => Promise.resolve({}) })
      )
    );
    render(withProviders(<ScenarioLibrary />));
    await screen.findByText(ru['scenarios.library.error']);
    expect(screen.queryByText(ru['scenarios.badge.submitted'])).toBeNull();
  });
});

describe('the library shows what the artifact already measured', () => {
  it('reports how far the run sits from the training range, against its threshold', async () => {
    const { container } = await renderLibrary();
    const submitted = container.querySelector('[data-scenario-id="final"]') as HTMLElement;

    expect(submitted.textContent).toContain(ru['scenarios.library.oodLabel']);
    expect(submitted.textContent).toContain('0,18');
    expect(submitted.textContent).toContain(
      ru['scenarios.library.oodOk'].replace('{threshold}', '0,5')
    );
  });

  it('names the worst regret and the scenario that produced it', async () => {
    const { container } = await renderLibrary();
    const submitted = container.querySelector('[data-scenario-id="final"]') as HTMLElement;

    expect(submitted.textContent).toContain(ru['scenarios.library.regretLabel']);
    expect(submitted.textContent).toContain('holdout-outage');
  });

  it('says a missing NPV was never measured instead of hiding the row', async () => {
    const { container } = await renderLibrary();
    const whatIf = container.querySelector('[data-scenario-id="what_if"]') as HTMLElement;

    expect(whatIf.textContent).toContain(ru['scenarios.library.npvLabel']);
    expect(whatIf.textContent).toContain(ru['scenarios.library.npvMissing']);
    expect(whatIf.querySelector('.scenarios-item-missing')).not.toBeNull();
  });

  it('shows no ood or regret line for a scenario that has neither', async () => {
    const { container } = await renderLibrary();
    const whatIf = container.querySelector('[data-scenario-id="what_if"]') as HTMLElement;

    expect(whatIf.textContent).not.toContain(ru['scenarios.library.oodLabel']);
    expect(whatIf.textContent).not.toContain(ru['scenarios.library.regretLabel']);
  });

  it('marks the first scenario active on a cold load, with no click needed', async () => {
    const { container } = await renderLibrary();
    const submitted = container.querySelector('[data-scenario-id="final"]') as HTMLElement;

    expect(submitted.getAttribute('data-active')).toBe('true');
    expect(submitted.getAttribute('aria-pressed')).toBe('true');
    expect(submitted.textContent).toContain(ru['scenarios.library.active']);
  });
});
