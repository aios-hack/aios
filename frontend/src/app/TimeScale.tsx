import { useMemo } from 'react';
import { useI18n } from '../i18n/I18nContext';
import { useTimeline } from '../state/TimelineContext';
import { formatStepDate } from '../ui/format';
import { StepControls } from '../views/Timeline/StepControls';
import { eventMarks, fieldEvents, yearTicks } from './events';
import { TimeScaleTrack } from './TimeScaleTrack';
import { useHotkeys } from './useHotkeys';
import { PLAY_SPEEDS, useStepPlayback } from './useStepPlayback';
import './TimeScale.css';

export const TimeScale = () => {
  const { t, lang } = useI18n();
  const { timeline, stepIndex, setStepIndex } = useTimeline();
  const steps = timeline.status === 'ready' ? timeline.data.steps : [];
  const stepCount = steps.length;
  const current = stepCount === 0 ? 0 : Math.min(stepIndex, stepCount - 1);
  const { playing, speed, setSpeed, selectStep, onStep, togglePlay } = useStepPlayback(
    stepCount,
    current,
    setStepIndex
  );

  useHotkeys({
    steps,
    stepIndex: current,
    onStep,
    onSelect: selectStep,
    onTogglePlay: togglePlay
  });

  const ticks = useMemo(() => yearTicks(steps), [steps]);
  const marks = useMemo(() => eventMarks(fieldEvents(steps)), [steps]);

  if (stepCount === 0) {
    return (
      <section className="time-scale" data-testid="time-scale" aria-label={t('steps.scaleLabel')}>
        <p className="time-scale-empty">{t('steps.scaleEmpty')}</p>
      </section>
    );
  }

  const step = steps[current];

  return (
    <section className="time-scale" data-testid="time-scale" aria-label={t('steps.scaleLabel')}>
      <TimeScaleTrack
        steps={steps}
        stepIndex={current}
        ticks={ticks}
        marks={marks}
        onSelect={selectStep}
      />
      <div className="time-scale-bar">
        <StepControls
          steps={steps}
          stepIndex={current}
          playing={playing}
          label={false}
          onSelect={selectStep}
          onStep={onStep}
          onTogglePlay={togglePlay}
        />
        <div className="time-scale-speed" role="group" aria-label={t('palette.speed')}>
          {PLAY_SPEEDS.map((value) => (
            <button
              key={value}
              type="button"
              className="time-scale-speed-button"
              aria-pressed={value === speed}
              data-testid={`speed-${value}`}
              onClick={() => setSpeed(value)}
            >
              {t('palette.speedValue', { value })}
            </button>
          ))}
        </div>
        <p className="time-scale-readout">
          <span className="time-scale-date">{formatStepDate(lang, step.date)}</span>
          <span className="time-scale-position">
            {t('steps.position', { step: current + 1, total: stepCount })}
          </span>
          {step.terminal && (
            <span className="timeline-terminal-badge">{t('steps.terminalBadge')}</span>
          )}
        </p>
      </div>
    </section>
  );
};
