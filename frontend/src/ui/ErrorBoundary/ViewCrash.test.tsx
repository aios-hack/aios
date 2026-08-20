import { render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { NpvFile } from '../../api/types';
import { dictionaries } from '../../i18n/dictionaries';
import { I18nProvider } from '../../i18n/I18nContext';
import { TimelineProvider } from '../../state/TimelineContext';
import { NpvRank } from '../../views/NpvRank';
import * as sorting from '../../views/NpvRank/sorting';
import { ErrorBoundary } from './ErrorBoundary';

const { ru, en } = dictionaries;

const npvFixture: NpvFile = {
  wells: [{ well: '10', pre_tax: 50, with_allocated_tax: 40 }],
  total: { pre_tax: 50, with_allocated_tax: 40 },
  npv_methodology: 40
};

const mockFetch = () => {
  vi.stubGlobal(
    'fetch',
    vi.fn((url: string) =>
      Promise.resolve({
        ok: true,
        json: () => Promise.resolve(url.includes('npv') ? npvFixture : {})
      })
    )
  );
};

const renderGuardedView = () =>
  render(
    <I18nProvider>
      <TimelineProvider>
        <ErrorBoundary>
          <NpvRank />
        </ErrorBoundary>
      </TimelineProvider>
    </I18nProvider>
  );

beforeEach(() => {
  localStorage.clear();
  mockFetch();
  vi.spyOn(console, 'error').mockImplementation(() => {});
});

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe('ErrorBoundary around a real view', () => {
  it('replaces a crashing view with a readable message instead of a blank panel', async () => {
    vi.spyOn(sorting, 'sortNpvRows').mockImplementation(() => {
      throw new Error('sort blew up');
    });

    const { container } = renderGuardedView();

    await screen.findByText(ru['boundary.title']);
    const alert = screen.getByRole('alert');
    expect(alert.textContent).toContain('sort blew up');
    expect(container.querySelector('table')).toBeNull();
    expect(container.textContent).not.toBe('');
  });

  it('reports the crash to the console so the failure is diagnosable', async () => {
    const spy = vi.spyOn(console, 'error').mockImplementation(() => {});
    vi.spyOn(sorting, 'sortNpvRows').mockImplementation(() => {
      throw new Error('sort blew up');
    });

    renderGuardedView();

    await screen.findByText(ru['boundary.title']);
    expect(
      spy.mock.calls.some((call) =>
        String(call[0]).includes('ErrorBoundary caught a render error')
      )
    ).toBe(true);
  });

  it('renders the boundary message in english when that locale is active', async () => {
    localStorage.setItem('aios-lang', 'en');
    vi.spyOn(sorting, 'sortNpvRows').mockImplementation(() => {
      throw new Error('sort blew up');
    });

    renderGuardedView();

    await screen.findByText(en['boundary.title']);
    expect(screen.queryByText(ru['boundary.title'])).toBeNull();
  });

  it('leaves a healthy view untouched', async () => {
    const { container } = renderGuardedView();
    await waitFor(() => expect(container.querySelector('table')).not.toBeNull());
    expect(screen.queryByText(ru['boundary.title'])).toBeNull();
  });
});
