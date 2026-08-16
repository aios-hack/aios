import type { TimelineStep } from '../../api/types';
import { useI18n } from '../../i18n/I18nContext';
import { Slider } from '../../ui/Slider';
import { formatStepDate } from './format';

interface StepControlsProps {
  steps: TimelineStep[];
  stepIndex: number;
  playing: boolean;
  onSelect: (index: number) => void;
  onStep: (delta: number) => void;
  onTogglePlay: () => void;
}

export const StepControls = ({
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

  return (
    <div className="timeline-controls">
      <div className="timeline-buttons">
        <button
          type="button"
          className="timeline-button"
          onClick={() => onStep(-1)}
          disabled={stepIndex === 0}
        >
          {t('steps.prev')}
        </button>
        <button type="button" className="timeline-button" onClick={onTogglePlay}>
          {playing ? t('steps.pause') : t('steps.play')}
        </button>
        <button
          type="button"
          className="timeline-button"
          onClick={() => onStep(1)}
          disabled={stepIndex === last}
        >
          {t('steps.next')}
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
        <span>{t('steps.position', { step: stepIndex + 1, total: steps.length })}</span>
        <span className="timeline-step-date">{formatStepDate(lang, step.date)}</span>
        {step.terminal && (
          <span className="timeline-terminal-badge">{t('steps.terminalBadge')}</span>
        )}
      </p>
    </div>
  );
};
