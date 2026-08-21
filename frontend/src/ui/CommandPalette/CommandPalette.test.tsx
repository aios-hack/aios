import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { ScenariosFile, TimelineFile, TimelineWellRow } from '../../api/types';
import { TimeScale } from '../../app/TimeScale';
import { stepForYearShift } from '../../app/useHotkeys';
import { PLAY_INTERVAL_MS, PLAY_SPEEDS, playIntervalMs } from '../../app/useStepPlayback';
import { dictionaries } from '../../i18n/dictionaries';
import { I18nProvider } from '../../i18n/I18nContext';
import { ConsoleProvider } from '../../state/ConsoleContext';
import { PlaybackProvider } from '../../state/PlaybackContext';
import { ScenarioProvider } from '../../state/ScenarioContext';
import { TimelineProvider, useTimeline } from '../../state/TimelineContext';
import { ThemeProvider } from '../../theme/ThemeContext';
import { CommandPalette } from './CommandPalette';
import { nearestStepByDate, wellCommands } from './commands';

const { ru } = dictionaries;

const WELLS = ['P10', 'P2', 'I1'];

const wellRow = (well: string, k: number): TimelineWellRow => ({
  well,
  availability: 'AVAILABLE',
  role: well.startsWith('I') ? 'INJ' : 'PROD',
  operating_status: 'OPEN',
  setpoint: 50,
  liquid_rate: well.startsWith('I') ? 0 : 40 + k,
  injection_rate: well.startsWith('I') ? 120 + k : 0,
  bhp: 90 + k,
  watercut: well.startsWith('I') ? null : 0.3,
  fact_to_target: 0.9,
  cumulative_liquid: 100 * (k + 1)
});

const STEP_COUNT = 30;

const timelineFixture: TimelineFile = {
  model: 'Model_Z',
  t0: '2007-01-01',
  n_control_dates: STEP_COUNT,
  n_intervals: STEP_COUNT - 1,
  wells: WELLS,
  steps: Array.from({ length: STEP_COUNT }, (_, k) => ({
    control_step: k,
    date: `${2007 + Math.floor(k / 12)}-${String((k % 12) + 1).padStart(2, '0')}-01`,
    terminal: k === STEP_COUNT - 1,
    field: {
      production: 2000 + k,
      injection: 1500 + k,
      compensation: 0.75,
      npv_cumulative: 1000 * (k + 1),
      active_wells: WELLS.length
    },
    wells: WELLS.map((well) => wellRow(well, k))
  }))
};

const scenariosFixture: ScenariosFile = {
  submitted: 'base',
  scenarios: [
    {
      id: 'base',
      config_hash: 'hash-base',
      converged: true,
      self_consistent: true,
      is_submitted: true,
      npv_methodology: 100,
      constraints: {
        injection_limits: 0,
        liquid_limits: 0,
        production_floors: 0,
        watercut_limits: 0,
        well_outages: 0,
        infrastructure: 0,
        years: [2007],
        outage_wells: [],
        empty: true
      }
    }
  ]
};

const mockFetch = () => {
  vi.stubGlobal(
    'fetch',
    vi.fn((url: string) => {
      const payload = url.includes('scenarios')
        ? scenariosFixture
        : url.includes('timeline')
          ? timelineFixture
          : {};
      return Promise.resolve({ ok: true, json: () => Promise.resolve(payload) });
    })
  );
};

const SelectionProbe = () => {
  const { selectedWell, stepIndex } = useTimeline();
  return (
    <p>
      <span data-testid="selected-well">{selectedWell ?? ''}</span>
      <span data-testid="step-index">{stepIndex}</span>
    </p>
  );
};

const renderPalette = () =>
  render(
    <ThemeProvider>
      <I18nProvider>
        <ScenarioProvider>
          <TimelineProvider>
            <PlaybackProvider>
              <ConsoleProvider>
                <SelectionProbe />
                <CommandPalette />
              </ConsoleProvider>
            </PlaybackProvider>
          </TimelineProvider>
        </ScenarioProvider>
      </I18nProvider>
    </ThemeProvider>
  );

const renderScale = () =>
  render(
    <ThemeProvider>
      <I18nProvider>
        <ScenarioProvider>
          <TimelineProvider>
            <PlaybackProvider>
              <SelectionProbe />
              <TimeScale />
            </PlaybackProvider>
          </TimelineProvider>
        </ScenarioProvider>
      </I18nProvider>
    </ThemeProvider>
  );

const openPalette = () =>
  fireEvent.keyDown(window, { key: 'k', ctrlKey: true });

beforeEach(() => {
  localStorage.clear();
  mockFetch();
});

afterEach(() => {
  vi.unstubAllGlobals();
  vi.useRealTimers();
});

describe('command sources', () => {
  it('orders wells with compareWellIds instead of string order', () => {
    expect(wellCommands(WELLS).map((command) => command.label)).toEqual([
      'I1',
      'P2',
      'P10'
    ]);
  });

  it('resolves a year and a year-month query to the nearest step in the data', () => {
    expect(nearestStepByDate(timelineFixture.steps, '2008')).toBe(12);
    expect(nearestStepByDate(timelineFixture.steps, '2008-03')).toBe(14);
    expect(nearestStepByDate(timelineFixture.steps, 'P2')).toBeNull();
  });
});

describe('command palette', () => {
  it('changes the selected well when a well number is typed and confirmed', async () => {
    renderPalette();
    await waitFor(() => expect(screen.queryByTestId('step-index')).toBeTruthy());
    openPalette();
    const input = await screen.findByRole('combobox');
    fireEvent.change(input, { target: { value: 'P10' } });
    const option = await screen.findByRole('option', { name: /P10/ });
    expect(option.getAttribute('aria-selected')).toBe('true');
    fireEvent.keyDown(input, { key: 'Enter' });
    await waitFor(() =>
      expect(screen.getByTestId('selected-well').textContent).toBe('P10')
    );
    expect(screen.queryByTestId('command-palette')).toBeNull();
  });

  it('jumps to the step nearest to a typed date', async () => {
    renderPalette();
    openPalette();
    const input = await screen.findByRole('combobox');
    fireEvent.change(input, { target: { value: '2008-03' } });
    fireEvent.keyDown(input, { key: 'Enter' });
    await waitFor(() => expect(screen.getByTestId('step-index').textContent).toBe('14'));
  });

  it('navigates with the arrows and closes on escape returning focus to the opener', async () => {
    renderPalette();
    const opener = document.createElement('button');
    document.body.appendChild(opener);
    opener.focus();
    openPalette();
    const input = await screen.findByRole('combobox');
    fireEvent.change(input, { target: { value: 'P' } });
    const options = await screen.findAllByRole('option');
    expect(options[0].getAttribute('aria-selected')).toBe('true');
    fireEvent.keyDown(input, { key: 'ArrowDown' });
    await waitFor(() =>
      expect(screen.getAllByRole('option')[1].getAttribute('aria-selected')).toBe('true')
    );
    fireEvent.keyDown(input, { key: 'Escape' });
    await waitFor(() => expect(screen.queryByTestId('command-palette')).toBeNull());
    expect(document.activeElement).toBe(opener);
    opener.remove();
  });

  it('opens and closes on the ctrl+k shortcut', async () => {
    renderPalette();
    openPalette();
    expect(await screen.findByTestId('command-palette')).toBeTruthy();
    fireEvent.keyDown(window, { key: 'k', metaKey: true });
    await waitFor(() => expect(screen.queryByTestId('command-palette')).toBeNull());
  });
});

describe('playback speed', () => {
  it('divides the base interval by the multiplier', () => {
    expect(playIntervalMs(1)).toBe(PLAY_INTERVAL_MS);
    expect(playIntervalMs(4)).toBe(PLAY_INTERVAL_MS / 4);
    expect(playIntervalMs(16)).toBe(Math.round(PLAY_INTERVAL_MS / 16));
  });

  it('changes the timer interval when the speed is switched', async () => {
    const setInterval = vi.spyOn(window, 'setInterval');
    const playbackIntervals = () =>
      setInterval.mock.calls
        .map((call) => call[1])
        .filter((delay) => PLAY_SPEEDS.some((value) => playIntervalMs(value) === delay));
    renderScale();
    await screen.findByTestId('time-scale-track');

    fireEvent.click(screen.getByLabelText(ru['steps.play']));
    await waitFor(() => expect(playbackIntervals().length).toBeGreaterThan(0));
    expect(playbackIntervals().at(-1)).toBe(PLAY_INTERVAL_MS);

    fireEvent.click(screen.getByTestId('speed-16'));
    await waitFor(() => expect(playbackIntervals().at(-1)).toBe(playIntervalMs(16)));
    expect(playIntervalMs(16)).not.toBe(PLAY_INTERVAL_MS);
    setInterval.mockRestore();
  });
});

describe('console hotkeys', () => {
  it('starts and stops playback on space', async () => {
    renderScale();
    await screen.findByTestId('time-scale-track');
    expect(screen.getByLabelText(ru['steps.play'])).toBeTruthy();

    fireEvent.keyDown(window, { key: ' ' });
    await waitFor(() => expect(screen.getByLabelText(ru['steps.pause'])).toBeTruthy());

    fireEvent.keyDown(window, { key: ' ' });
    await waitFor(() => expect(screen.getByLabelText(ru['steps.play'])).toBeTruthy());
  });

  it('moves one step with the arrows', async () => {
    renderScale();
    await screen.findByTestId('time-scale-track');
    fireEvent.keyDown(window, { key: 'ArrowRight' });
    await waitFor(() => expect(screen.getByTestId('step-index').textContent).toBe('1'));
    fireEvent.keyDown(window, { key: 'ArrowLeft' });
    await waitFor(() => expect(screen.getByTestId('step-index').textContent).toBe('0'));
  });

  it('moves a year by the dates in the data, not by a step count literal', async () => {
    renderScale();
    await screen.findByTestId('time-scale-track');
    fireEvent.keyDown(window, { key: ']' });
    await waitFor(() => expect(screen.getByTestId('step-index').textContent).toBe('12'));
    fireEvent.keyDown(window, { key: '[' });
    await waitFor(() => expect(screen.getByTestId('step-index').textContent).toBe('0'));
  });

  it('stays inert while the focus is inside a text field', async () => {
    renderScale();
    await screen.findByTestId('time-scale-track');
    const field = document.createElement('input');
    document.body.appendChild(field);
    field.focus();
    fireEvent.keyDown(field, { key: ' ' });
    fireEvent.keyDown(field, { key: 'ArrowRight' });
    expect(screen.getByLabelText(ru['steps.play'])).toBeTruthy();
    expect(screen.getByTestId('step-index').textContent).toBe('0');
    field.remove();
  });
});

describe('year navigation model', () => {
  it('lands on the first step of the neighbouring year found in the dates', () => {
    const steps = timelineFixture.steps;
    expect(stepForYearShift(steps, 0, 1)).toBe(12);
    expect(stepForYearShift(steps, 14, -1)).toBe(0);
    expect(stepForYearShift(steps, steps.length - 1, 1)).toBe(steps.length - 1);
    expect(stepForYearShift([], 0, 1)).toBe(0);
  });
});
