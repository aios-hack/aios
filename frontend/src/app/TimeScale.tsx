import { useMemo, useRef } from 'react';
import { useI18n } from '../i18n/I18nContext';
import { useTimeline } from '../state/TimelineContext';
import { formatStepDate } from '../ui/format';
import { PlaybackSettings } from '../ui/PlaybackSettings';
import { StepControls } from '../views/Timeline/StepControls';
import { eventMarks, fieldEvents, yearTicks } from './events';
import { TimeScaleTrack } from './TimeScaleTrack';
import { useBackdropMorph } from './useBackdropMorph';
import { useAxisCollapse } from './useAxisCollapse';
import { useBackdropShape } from './useBackdropShape';
import { useHotkeys } from './useHotkeys';
import { playIntervalMs, useStepPlayback } from './useStepPlayback';
import './TimeScale.css';

export const TimeScale = () => {
  const { t, lang } = useI18n();
  const { timeline, stepIndex, setStepIndex } = useTimeline();
  const steps = timeline.status === 'ready' ? timeline.data.steps : [];
  const stepCount = steps.length;
  const current = stepCount === 0 ? 0 : Math.min(stepIndex, stepCount - 1);
  const { playing, speed, showDate, settingsOpen, selectStep, onStep, togglePlay } = useStepPlayback(
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

  const scaleRef = useRef<HTMLElement | null>(null);
  const { collapsed, toggle, onPointerDown } = useAxisCollapse();
  const shape = useBackdropShape(scaleRef, settingsOpen);
  const PAD = 22;
  const RAMP = 132;
  const TOP = 22;
  const SHELF = 84;
  const plateauLeft = shape.left - PAD;
  const plateauRight = shape.right + PAD;
  const backdropPath = [
    `M0 148 L0 ${SHELF}`,
    `L${Math.round(plateauLeft - RAMP)} ${SHELF}`,
    `C${Math.round(plateauLeft - RAMP * 0.45)} ${SHELF} ${Math.round(plateauLeft - RAMP * 0.55)} ${TOP} ${Math.round(plateauLeft)} ${TOP}`,
    `L${Math.round(plateauRight)} ${TOP}`,
    `C${Math.round(plateauRight + RAMP * 0.55)} ${TOP} ${Math.round(plateauRight + RAMP * 0.45)} ${SHELF} ${Math.round(plateauRight + RAMP)} ${SHELF}`,
    `L${shape.width} ${SHELF} L${shape.width} 148 Z`
  ].join(' ');
  const backdropRef = useBackdropMorph(backdropPath, 260);

  const ticks = useMemo(() => yearTicks(steps), [steps]);
  const marks = useMemo(() => eventMarks(fieldEvents(steps)), [steps]);

  if (stepCount === 0) {
    return (
      <section
      ref={scaleRef}
      className="time-scale"
      data-testid="time-scale"
      aria-label={t('steps.scaleLabel')}
    >
        <p className="time-scale-empty">{t('steps.scaleEmpty')}</p>
      </section>
    );
  }

  const step = steps[current];

  return (
    <section
      ref={scaleRef}
      className="time-scale"
      data-testid="time-scale"
      data-collapsed={collapsed ? 'true' : undefined}
      aria-label={t('steps.scaleLabel')}
    >
      <button
        type="button"
        className="time-scale-grip"
        aria-expanded={!collapsed}
        aria-label={t(collapsed ? 'steps.expandAxis' : 'steps.collapseAxis')}
        title={t(collapsed ? 'steps.expandAxis' : 'steps.collapseAxis')}
        data-testid="time-scale-grip"
        onPointerDown={onPointerDown}
        onKeyDown={(event) => {
          if (event.key === 'Enter' || event.key === ' ') {
            event.preventDefault();
            toggle();
          }
        }}
      >
        <span className="time-scale-grip-bar" aria-hidden="true" />
      </button>
      <svg
        className="time-scale-backdrop"
        viewBox={`0 0 ${shape.width} 148`}
        aria-hidden="true"
      >
        <path ref={backdropRef} d={backdropPath} />
      </svg>
      <div className="time-scale-player">
        <div className="time-scale-controls">
          {showDate && (
            <p className="time-scale-readout time-scale-island">
              <span className="time-scale-date">
                {step.terminal ? t('steps.terminalShort') : formatStepDate(lang, step.date)}
              </span>
            </p>
          )}
          <span className="time-scale-position visually-hidden">
            {t('steps.position', { step: current + 1, total: stepCount })}
          </span>
          <StepControls
            steps={steps}
            stepIndex={current}
            playing={playing}
            label={false}
            slider={false}
            onSelect={selectStep}
            onStep={onStep}
            onTogglePlay={togglePlay}
          />
          <div className="icon-island playback-settings-island">
            <PlaybackSettings />
          </div>
        </div>
      </div>
      <TimeScaleTrack
        steps={steps}
        stepIndex={current}
        ticks={ticks}
        marks={marks}
        glideMs={playing ? playIntervalMs(speed) : 0}
        onSelect={selectStep}
      />
    </section>
  );
};
