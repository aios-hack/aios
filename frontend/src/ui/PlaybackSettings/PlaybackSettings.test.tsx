import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { I18nProvider } from '../../i18n/I18nContext';
import { PlaybackProvider, usePlayback } from '../../state/PlaybackContext';
import { ScenarioProvider } from '../../state/ScenarioContext';
import { TimelineProvider } from '../../state/TimelineContext';
import { ThemeProvider } from '../../theme/ThemeContext';
import { PlaybackSettings } from './PlaybackSettings';

const Probe = () => {
  const { speed, showDate } = usePlayback();
  return (
    <p>
      <span data-testid="probe-speed">{speed}</span>
      <span data-testid="probe-show-date">{showDate ? 'yes' : 'no'}</span>
    </p>
  );
};

const renderSettings = () => {
  vi.stubGlobal(
    'fetch',
    vi.fn(() => Promise.resolve({ ok: true, json: () => Promise.resolve({}) }))
  );
  return render(
    <ThemeProvider>
      <I18nProvider>
        <ScenarioProvider>
          <TimelineProvider>
            <PlaybackProvider>
              <Probe />
              <PlaybackSettings />
            </PlaybackProvider>
          </TimelineProvider>
        </ScenarioProvider>
      </I18nProvider>
    </ThemeProvider>
  );
};

const openPanel = () => {
  fireEvent.click(screen.getByTestId('playback-settings-trigger'));
};

describe('playback settings', () => {
  it('stays closed until the trigger is used', () => {
    renderSettings();
    expect(screen.queryByTestId('playback-settings')).toBeNull();
    openPanel();
    expect(screen.getByTestId('playback-settings')).toBeTruthy();
  });

  it('offers a fine quarter-to-three speed range on a single slider', () => {
    renderSettings();
    openPanel();
    const slider = screen
      .getByTestId('playback-settings')
      .querySelector('input[type="range"]') as HTMLInputElement;
    expect(slider.min).toBe('0.25');
    expect(slider.max).toBe('3');
    expect(slider.step).toBe('0.05');
  });

  it('moves the playback speed with the slider', async () => {
    renderSettings();
    openPanel();
    const slider = screen
      .getByTestId('playback-settings')
      .querySelector('input[type="range"]') as HTMLInputElement;
    fireEvent.change(slider, { target: { value: '0.25' } });
    await waitFor(() => expect(screen.getByTestId('probe-speed').textContent).toBe('0.25'));
  });

  it('toggles the month readout both ways', async () => {
    renderSettings();
    openPanel();
    expect(screen.getByTestId('probe-show-date').textContent).toBe('yes');
    fireEvent.click(screen.getByTestId('playback-settings-date'));
    await waitFor(() => expect(screen.getByTestId('probe-show-date').textContent).toBe('no'));
    fireEvent.click(screen.getByTestId('playback-settings-date'));
    await waitFor(() => expect(screen.getByTestId('probe-show-date').textContent).toBe('yes'));
  });
});
