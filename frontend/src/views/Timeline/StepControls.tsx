import {
  PauseIcon,
  PlayIcon,
  SkipBackIcon,
  SkipForwardIcon,
  RewindIcon,
  FastForwardIcon
} from '@phosphor-icons/react';
import { memo } from 'react';
import type { TimelineStep } from '../../api/types';
import { useI18n } from '../../i18n/I18nContext';
import { Slider } from '../../ui/Slider';
import { formatStepDate } from '../../ui/format';

interface StepControlsProps {
  steps: TimelineStep[];
  stepIndex: number;
  playing: boolean;
  onSelect: (index: number) => void;
  onStep: (delta: number) => void;
  onTogglePlay: () => void;
}

const StepControlsView = ({
  steps,
  stepIndex,
  playing,
  onSelect,
  onStep,
  onTogglePlay
}: StepControlsProps) => {
  const { t, lang } = useI18n();
  const last = steps.length - 1;
  const step = steps[stepIndex];
  const atStart = stepIndex === 0;
  const atEnd = stepIndex === last;

  return (
    <div className="timeline-controls">
      <div className="timeline-transport" role="group" aria-label={t('steps.transport')}>
        <button
          type="button"
          className="transport-button"
          onClick={() => onSelect(0)}
          disabled={atStart}
          aria-label={t('steps.first')}
          title={t('steps.first')}
        >
          <SkipBackIcon size={18} weight="fill" aria-hidden="true" />
        </button>
        <button
          type="button"
          className="transport-button"
          onClick={() => onStep(-1)}
          disabled={atStart}
          aria-label={t('steps.prev')}
          title={t('steps.prev')}
        >
          <RewindIcon size={18} weight="fill" aria-hidden="true" />
        </button>
        <button
          type="button"
          className="transport-button transport-button--play"
          onClick={onTogglePlay}
          aria-label={playing ? t('steps.pause') : t('steps.play')}
          title={playing ? t('steps.pause') : t('steps.play')}
          data-playing={playing}
        >
          {playing ? (
            <PauseIcon size={22} weight="fill" aria-hidden="true" />
          ) : (
            <PlayIcon size={22} weight="fill" aria-hidden="true" />
          )}
        </button>
        <button
          type="button"
          className="transport-button"
          onClick={() => onStep(1)}
          disabled={atEnd}
          aria-label={t('steps.next')}
          title={t('steps.next')}
        >
          <FastForwardIcon size={18} weight="fill" aria-hidden="true" />
        </button>
        <button
          type="button"
          className="transport-button"
          onClick={() => onSelect(last)}
          disabled={atEnd}
          aria-label={t('steps.last')}
          title={t('steps.last')}
        >
          <SkipForwardIcon size={18} weight="fill" aria-hidden="true" />
        </button>
      </div>
      <Slider
        className="timeline-slider"
        min={0}
        max={last}
        step={1}
        value={stepIndex}
        ariaLabel={t('steps.sliderLabel')}
        onChange={onSelect}
      />
      <p className="timeline-step-label">
        <span className="timeline-step-position">
          {t('steps.position', { step: stepIndex + 1, total: steps.length })}
        </span>
        <span className="timeline-step-date">{formatStepDate(lang, step.date)}</span>
        {step.terminal && (
          <span className="timeline-terminal-badge">{t('steps.terminalBadge')}</span>
        )}
      </p>
    </div>
  );
};

export const StepControls = memo(StepControlsView);
