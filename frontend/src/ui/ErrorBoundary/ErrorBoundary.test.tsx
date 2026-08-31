import { render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { InvalidPayloadError } from '../../data/fetchJson';
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
    expect(screen.getByText(ru['boundary.hint'])).toBeTruthy();
  });

  it('keeps the exception message out of the rendered output', () => {
    vi.spyOn(console, 'error').mockImplementation(() => {});
    render(
      <I18nProvider>
        <ErrorBoundary>
          <Boom />
        </ErrorBoundary>
      </I18nProvider>
    );
    expect(screen.getByRole('alert').textContent).not.toContain('render exploded');
  });

  it('keeps an artifact url out of the rendered output', () => {
    vi.spyOn(console, 'error').mockImplementation(() => {});
    const Leaky = (): never => {
      throw new InvalidPayloadError('/data/policy-plan/npv.json');
    };
    render(
      <I18nProvider>
        <ErrorBoundary>
          <Leaky />
        </ErrorBoundary>
      </I18nProvider>
    );
    const text = screen.getByRole('alert').textContent ?? '';
    expect(text).not.toContain('/data/');
    expect(text).not.toContain('npv.json');
    expect(text).toContain(ru['boundary.hint']);
  });

  it('still renders a status when the i18n provider itself is missing', () => {
    vi.spyOn(console, 'error').mockImplementation(() => {});
    render(
      <ErrorBoundary>
        <Boom />
      </ErrorBoundary>
    );
    expect(screen.getByRole('alert')).toBeTruthy();
    expect(screen.getByText(ru['boundary.title'])).toBeTruthy();
  });

  it('still reports the error to the console for developers', () => {
    const spy = vi.spyOn(console, 'error').mockImplementation(() => {});
    render(
      <I18nProvider>
        <ErrorBoundary>
          <Boom />
        </ErrorBoundary>
      </I18nProvider>
    );
    const logged = spy.mock.calls.some((call) =>
      call.some((arg) => arg instanceof Error && arg.message === 'render exploded')
    );
    expect(logged).toBe(true);
  });
});
