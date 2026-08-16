import { render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { dictionaries } from '../../i18n/dictionaries';
import { I18nProvider } from '../../i18n/I18nContext';
import { ErrorBoundary } from './ErrorBoundary';

const { ru } = dictionaries;

const Boom = (): never => {
  throw new Error('render exploded');
};

afterEach(() => {
  vi.restoreAllMocks();
});

describe('ErrorBoundary', () => {
  it('renders children while nothing throws', () => {
    render(
      <I18nProvider>
        <ErrorBoundary>
          <p>content</p>
        </ErrorBoundary>
      </I18nProvider>
    );
    expect(screen.getByText('content')).toBeTruthy();
  });

  it('shows a translated status instead of a blank screen when a child throws', () => {
    vi.spyOn(console, 'error').mockImplementation(() => {});
    render(
      <I18nProvider>
        <ErrorBoundary>
          <Boom />
        </ErrorBoundary>
      </I18nProvider>
    );
    expect(screen.getByText(ru['boundary.title'])).toBeTruthy();
    expect(screen.getByRole('alert')).toBeTruthy();
    expect(screen.getByRole('alert').textContent).toContain('render exploded');
  });
});
