import { act, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { TimelineFile, TimelineStep } from '../api/types';
import { I18nProvider } from '../i18n/I18nContext';
import { TimelineProvider, useTimeline } from './TimelineContext';

const step = (k: number): TimelineStep => ({
  control_step: k,
  date: `2007-0${k + 1}-01`,
  terminal: false,
  field: {
    production: 1,
    injection: 1,
    compensation: 1,
    npv_cumulative: 1,
    active_wells: 1
  },
  wells: [
    {
      well: '10',
      availability: 'AVAILABLE',
      role: 'PROD',
      operating_status: 'OPEN',
      setpoint: 1,
      liquid_rate: 1,
      injection_rate: 0,
      bhp: 1,
      watercut: 0.5,
      fact_to_target: 1,
      cumulative_liquid: 1
    }
  ]
});

const fixture: TimelineFile = {
  model: 'Model_Z',
  t0: '2007-01-01',
  n_control_dates: 2,
  n_intervals: 1,
  wells: ['10'],
  steps: [step(0), step(1)]
};

let setStepIndex: ((value: number) => void) | null = null;

const Probe = () => {
  const { stepIndex, timeline, setStepIndex: set } = useTimeline();
  setStepIndex = set;
  return (
    <>
      <span data-testid="probe-index">{stepIndex}</span>
      <span data-testid="probe-status">{timeline.status}</span>
    </>
  );
};

beforeEach(() => {
  localStorage.clear();
  setStepIndex = null;
  vi.stubGlobal(
    'fetch',
    vi.fn((url: string) =>
      Promise.resolve({
        ok: true,
        json: () => Promise.resolve(url.includes('timeline.json') ? fixture : {})
      })
    )
  );
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe('TimelineContext', () => {
  it('clamps the shared step index to the loaded step count', async () => {
    render(
      <I18nProvider>
        <TimelineProvider>
          <Probe />
        </TimelineProvider>
      </I18nProvider>
    );
    await waitFor(() => expect(screen.getByTestId('probe-status').textContent).toBe('ready'));

    act(() => setStepIndex?.(99));

    await waitFor(() => expect(screen.getByTestId('probe-index').textContent).toBe('1'));

    act(() => setStepIndex?.(-5));

    await waitFor(() => expect(screen.getByTestId('probe-index').textContent).toBe('0'));
  });
});
