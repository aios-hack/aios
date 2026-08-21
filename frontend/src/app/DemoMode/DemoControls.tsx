import { FilmSlateIcon, PauseIcon, PlayIcon, StopIcon } from '@phosphor-icons/react';
import { useT } from '../../i18n/I18nContext';
import type { DemoPlayback } from './useDemoPlayback';

export const DemoControls = ({ playback }: { playback: DemoPlayback }) => {
  const t = useT();
  const { script, active, playing, start, resume, pause, stop } = playback;

  if (script === null || script.frames.length === 0) {
    return null;
  }

  if (!active) {
    return (
      <button
        type="button"
        className="demo-button"
        data-demo-control="start"
        data-testid="demo-start"
        aria-label={t('demo.start')}
        title={t('demo.start')}
        onClick={start}
      >
        <FilmSlateIcon size={18} weight="fill" aria-hidden="true" />
      </button>
    );
  }

  return (
    <div className="demo-transport" role="group" aria-label={t('demo.label')}>
      <button
        type="button"
        className="demo-button"
        data-demo-control="toggle"
        data-testid="demo-toggle"
        aria-label={playing ? t('demo.pause') : t('demo.resume')}
        title={playing ? t('demo.pause') : t('demo.resume')}
        onClick={playing ? pause : resume}
      >
        {playing ? (
          <PauseIcon size={18} weight="fill" aria-hidden="true" />
        ) : (
          <PlayIcon size={18} weight="fill" aria-hidden="true" />
        )}
      </button>
      <button
        type="button"
        className="demo-button"
        data-demo-control="stop"
        data-testid="demo-stop"
        aria-label={t('demo.stop')}
        title={t('demo.stop')}
        onClick={stop}
      >
        <StopIcon size={18} weight="fill" aria-hidden="true" />
      </button>
    </div>
  );
};
