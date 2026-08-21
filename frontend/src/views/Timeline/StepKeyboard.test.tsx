import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import type { ReactNode } from 'react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { TimelineFile, TimelineWellRow } from '../../api/types';
import { dictionaries } from '../../i18n/dictionaries';
import { useT } from '../../i18n/I18nContext';
import { I18nProvider } from '../../i18n/I18nContext';
import { PlaybackProvider, usePlayback } from '../../state/PlaybackContext';
import { TimelineProvider, useTimeline } from '../../state/TimelineContext';
import { ViewStatus } from '../../ui/ViewStatus';
import { StepControls } from './StepControls';
import { WellsTable } from './WellsTable';

const { ru } = dictionaries;

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

const row = (well: string): TimelineWellRow => ({
  well,
  availability: 'AVAILABLE',
  role: 'PROD',
  operating_status: 'OPEN',
  setpoint: 50,
  liquid_rate: 70,
  injection_rate: 0,
  bhp: 91,
  watercut: 0.5,
  fact_to_target: 1.4,
  cumulative_liquid: 2100
});

const fixture: TimelineFile = {
  model: 'Model_Z',
  t0: '2007-01-01',
  n_control_dates: 4,
  n_intervals: 3,
  wells: ['11'],
  steps: Array.from({ length: 4 }, (_, k) => ({
    control_step: k,
    date: `2007-0${k + 1}-01`,
    terminal: k === 3,
    field: {
      production: k === 3 ? null : 2000 + k,
      injection: k === 3 ? null : 1500 + k,
      compensation: k === 3 ? null : 0.75,
      npv_cumulative: 1000 * (k + 1),
      active_wells: 1
    },
    wells: [row('11')]
  }))
};

const withProviders = (node: ReactNode) => (
  <I18nProvider>
    <TimelineProvider>
      <PlaybackProvider>{node}</PlaybackProvider>
    </TimelineProvider>
  </I18nProvider>
);

const mockFetch = () => {
  vi.stubGlobal(
    'fetch',
    vi.fn(() => Promise.resolve({ ok: true, json: () => Promise.resolve(fixture) }))
  );
};

const renderTimeline = async () => {
  const view = render(withProviders(<StepsTestView />));
  await waitFor(() =>
    expect(view.container.querySelector('input[type="range"]')).not.toBeNull()
  );
  return view;
};

const slider = (container: HTMLElement): HTMLInputElement =>
  container.querySelector('input[type="range"]') as HTMLInputElement;

const position = (step: number, total: number): string =>
  ru['steps.position'].replace('{step}', String(step)).replace('{total}', String(total));

beforeEach(() => {
  localStorage.clear();
  mockFetch();
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe('step navigation by keyboard and transport', () => {
  it('exposes the slider as a labelled range bounded by the step count', async () => {
    const { container } = await renderTimeline();
    const input = slider(container);
    expect(input.getAttribute('aria-label')).toBe(ru['steps.sliderLabel']);
    expect(input.min).toBe('0');
    expect(input.max).toBe('3');
  });

  it('is reachable by keyboard focus', async () => {
    const { container } = await renderTimeline();
    slider(container).focus();
    expect(document.activeElement).toBe(slider(container));
  });

  it('advances and rewinds one step through the transport buttons', async () => {
    await renderTimeline();
    expect(screen.getByText(position(1, 4))).toBeTruthy();

    fireEvent.click(screen.getByRole('button', { name: ru['steps.next'] }));
    expect(screen.getByText(position(2, 4))).toBeTruthy();

    fireEvent.click(screen.getByRole('button', { name: ru['steps.prev'] }));
    expect(screen.getByText(position(1, 4))).toBeTruthy();
  });

  it('disables the backward transport at the first step and forward at the last', async () => {
    const { container } = await renderTimeline();

    expect(screen.getByRole('button', { name: ru['steps.prev'] })).toHaveProperty(
      'disabled',
      true
    );
    expect(screen.getByRole('button', { name: ru['steps.first'] })).toHaveProperty(
      'disabled',
      true
    );

    fireEvent.click(screen.getByRole('button', { name: ru['steps.last'] }));

    expect(screen.getByText(position(4, 4))).toBeTruthy();
    expect(screen.getByRole('button', { name: ru['steps.next'] })).toHaveProperty(
      'disabled',
      true
    );
    expect(slider(container).value).toBe('3');
  });

  it('never moves past the terminal step when asked to go further', async () => {
    const { container } = await renderTimeline();
    fireEvent.click(screen.getByRole('button', { name: ru['steps.last'] }));
    fireEvent.change(slider(container), { target: { value: '99' } });

    expect(screen.getByText(position(4, 4))).toBeTruthy();
    expect(screen.getByText(ru['steps.terminalBadge'])).toBeTruthy();
    expect(container.textContent).not.toContain('NaN');
    expect(container.querySelectorAll('tbody tr')).toHaveLength(1);
  });

  it('keeps the transport labelled as a group for screen readers', async () => {
    await renderTimeline();
    expect(screen.getByRole('group', { name: ru['steps.transport'] })).toBeTruthy();
  });
});
