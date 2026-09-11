import { GearIcon } from '@phosphor-icons/react';
import { useId } from 'react';
import { useT } from '@/shared/i18n/I18nContext';
import { usePlayback, type PlaySpeed } from '@/entities/timeline/model/PlaybackContext';
import { IconButton } from '@/shared/ui/IconButton';
import { Popover } from '@/shared/ui/Popover';
import { Slider } from '@/shared/ui/Slider';
import './PlaybackSettings.css';

const formatSpeed = (speed: number): string =>
  Number.isInteger(speed) ? String(speed) : String(Number(speed.toFixed(2)));

export const PlaybackSettings = () => {
  const t = useT();
  const { speed, speedMin, speedMax, speedStep, showDate, setSettingsOpen, setShowDate, setSpeed } =
    usePlayback();
  const dateId = useId();
  const speedId = useId();

  return (
    <Popover
      label={t('playback.settings')}
      align="end"
      trigger={({ ref, open, onClick }) => (
        <IconButton
          ref={ref}
          className="playback-settings-trigger"
          data-guide="player-speed"
          label={t('playback.settings')}
          aria-expanded={open}
          data-testid="playback-settings-trigger"
          onClick={onClick}
        >
          <GearIcon size={22} weight="fill" aria-hidden="true" />
        </IconButton>
      )}
    >
      <div
        className="playback-settings"
        data-testid="playback-settings"
        ref={(node) => {
          setSettingsOpen(node !== null);
        }}
      >
        <div className="playback-settings-row">
          <label className="playback-settings-label" htmlFor={speedId}>
            {t('playback.speed')}
          </label>
          <Slider
            id={speedId}
            className="playback-settings-slider"
            min={speedMin}
            max={speedMax}
            step={speedStep}
            value={speed}
            ariaLabel={t('playback.speed')}
            onChange={(value) => setSpeed(value as PlaySpeed)}
          />
          <span className="playback-settings-value">
            {t('playback.speedValue', { value: formatSpeed(speed) })}
          </span>
        </div>
        <div className="playback-settings-row">
          <label className="playback-settings-label" htmlFor={dateId}>
            {t('playback.showDate')}
          </label>
          <span className="playback-switch">
            <input
              id={dateId}
              type="checkbox"
              className="playback-switch-input"
              checked={showDate}
              data-testid="playback-settings-date"
              onChange={(event) => setShowDate(event.target.checked)}
            />
            <span className="playback-switch-track" aria-hidden="true">
              <span className="playback-switch-thumb" />
            </span>
          </span>
        </div>
      </div>
    </Popover>
  );
};
