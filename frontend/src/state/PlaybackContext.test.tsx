import { act, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { TimelineFile } from '../api/types';
import { useStepPlayback } from '../app/useStepPlayback';
import { I18nProvider } from '../i18n/I18nContext';
import {
  PLAY_SPEED_MAX,
  PLAY_SPEED_MIN,
  PlaybackProvider,
  playIntervalMs
} from './PlaybackContext';
import { TimelineProvider } from './TimelineContext';

const fixture: TimelineFile = {
  model: 'Model_Z',
  t0: '2007-01-01',
  n_control_dates: 3,
  n_intervals: 2,
  wells: ['10'],
  steps: Array.from({ length: 3 }, (_, k) => ({
    control_step: k,
    date: `2007-0${k + 1}-01`,
    terminal: k === 2,
    field: {
      production: 2000 + k,
      injection: 1500 + k,
      compensation: 0.75,
      npv_cumulative: 1000 * (k + 1),
      active_wells: 1
    },
    wells: [
      {
        well: '10',
        availability: 'AVAILABLE',
        role: 'PROD',
        operating_status: 'OPEN',
        setpoint: 50,
        liquid_rate: 40 + k,
        injection_rate: 0,
        bhp: 90,
        watercut: 0.3,
        fact_to_target: 0.9,
        cumulative_liquid: 100 * (k + 1)
      }
    ]
  }))
};

const Consumer = ({ id }: { id: string }) => {
  const { playing, speed, setSpeed, togglePlay } = useStepPlayback();
  return (
    <div>
      <span data-testid={`playing-${id}`}>{String(playing)}</span>
      <span data-testid={`speed-${id}`}>{speed}</span>
      <button type="button" data-testid={`toggle-${id}`} onClick={togglePlay}>
        toggle
      </button>
      <button type="button" data-testid={`speed-up-${id}`} onClick={() => setSpeed(4)}>
        speed up
      </button>
      <button type="button" data-testid={`speed-down-${id}`} onClick={() => setSpeed(0)}>
        speed down
      </button>
    </div>
  );
};

const renderConsumers = () =>
  render(
    <I18nProvider>
      <TimelineProvider>
        <PlaybackProvider>
          <Consumer id="a" />
          <Consumer id="b" />
        </PlaybackProvider>
      </TimelineProvider>
    </I18nProvider>
  );

beforeEach(() => {
  localStorage.clear();
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

describe('shared playback state', () => {
  it('reflects a play toggled from one consumer in every other consumer', async () => {
    renderConsumers();
    await waitFor(() => expect(screen.getByTestId('playing-a').textContent).toBe('false'));
    expect(screen.getByTestId('playing-b').textContent).toBe('false');

    act(() => screen.getByTestId('toggle-a').click());

    expect(screen.getByTestId('playing-a').textContent).toBe('true');
    expect(screen.getByTestId('playing-b').textContent).toBe('true');

    act(() => screen.getByTestId('toggle-b').click());

    expect(screen.getByTestId('playing-a').textContent).toBe('false');
    expect(screen.getByTestId('playing-b').textContent).toBe('false');
  });

  it('reflects a speed change from one consumer in every other consumer', async () => {
    renderConsumers();
    await waitFor(() => expect(screen.getByTestId('speed-a').textContent).toBe('1'));
    expect(screen.getByTestId('speed-b').textContent).toBe('1');

    act(() => screen.getByTestId('speed-up-a').click());

    expect(screen.getByTestId('speed-a').textContent).toBe(String(PLAY_SPEED_MAX));
    expect(screen.getByTestId('speed-b').textContent).toBe(String(PLAY_SPEED_MAX));
  });

  it('clamps a speed outside the allowed range instead of accepting it', async () => {
    renderConsumers();
    await waitFor(() => expect(screen.getByTestId('speed-a').textContent).toBe('1'));

    act(() => screen.getByTestId('speed-down-a').click());

    expect(screen.getByTestId('speed-a').textContent).toBe(String(PLAY_SPEED_MIN));
    expect(playIntervalMs(Number(screen.getByTestId('speed-a').textContent))).toBeGreaterThan(0);
    expect(
      Number.isFinite(playIntervalMs(Number(screen.getByTestId('speed-a').textContent)))
    ).toBe(true);
  });

  it('advances the shared step from a single timer, not one per consumer', async () => {
    renderConsumers();
    await waitFor(() => expect(screen.getByTestId('playing-a').textContent).toBe('false'));

    vi.useFakeTimers();
    act(() => screen.getByTestId('toggle-a').click());
    expect(vi.getTimerCount()).toBe(1);

    await act(async () => {
      await vi.advanceTimersByTimeAsync(300);
    });
    expect(vi.getTimerCount()).toBe(1);

    vi.useRealTimers();
  });
});
