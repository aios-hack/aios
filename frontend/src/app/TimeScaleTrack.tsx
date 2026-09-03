import { memo, type CSSProperties } from 'react';
import type { TimelineStep } from '../api/types';
import { useT } from '../i18n/I18nContext';
import type { EventMark, YearTick } from './events';

const percentOf = (step: number, last: number): number =>
  last <= 0 ? 0 : (step / last) * 100;

interface TimeScaleTrackProps {
  steps: TimelineStep[];
  stepIndex: number;
  ticks: YearTick[];
  marks: EventMark[];
  glideMs: number;
  onSelect: (index: number) => void;
}

const TimeScaleTrackView = ({
  steps,
  stepIndex,
  ticks,
  marks,
  glideMs,
  onSelect
}: TimeScaleTrackProps) => {
  const t = useT();
  const last = steps.length - 1;
  const labelOf = (mark: EventMark): string =>
    t('steps.event', {
      date: steps[mark.step]?.date ?? '',
      count: mark.count,
      types: mark.types.map((type) => t(`steps.eventType.${type}`)).join(', ')
    });
  const progress = last <= 0 ? 0 : stepIndex / last;
  const trackStyle = {
    '--time-scale-progress': progress,
    '--time-scale-glide': `${glideMs}ms`
  } as CSSProperties;

  return (
    <div
      className="time-scale-track"
      data-testid="time-scale-track"
      data-guide="player-track"
      style={trackStyle}
    >
      <div className="time-scale-years" aria-hidden="true">
        {ticks.map((tick) => (
          <span
            key={tick.year}
            className="time-scale-year"
            data-year={tick.year}
            style={{ left: `${percentOf(tick.step, last)}%` }}
          >
            {tick.year}
          </span>
        ))}
      </div>
      <input
        className="time-scale-input"
        type="range"
        min={0}
        max={Math.max(last, 0)}
        step={1}
        value={stepIndex}
        aria-label={t('steps.sliderLabel')}
        onChange={(event) => onSelect(Number(event.target.value))}
      />
      <div className="time-scale-rail" aria-hidden="true">
        <span className="time-scale-fill" />
        <span className="time-scale-marks">
          {ticks.map((tick) => (
            <span
              key={tick.year}
              className="time-scale-mark"
              style={{ left: `${percentOf(tick.step, last)}%` }}
            />
          ))}
        </span>
        <span
          className="time-scale-cursor"
          data-testid="time-scale-cursor"
          data-step={stepIndex}
        />
      </div>
      <div className="time-scale-events" data-testid="time-scale-events">
        {marks.map((mark) => (
          <button
            key={mark.step}
            type="button"
            className="time-scale-event"
            data-event-step={mark.step}
            data-event-types={mark.types.join(' ')}
            style={{ left: `${percentOf(mark.step, last)}%` }}
            aria-label={labelOf(mark)}
            title={labelOf(mark)}
            onClick={(event) => {
              event.stopPropagation();
              onSelect(mark.step);
            }}
          />
        ))}
      </div>
    </div>
  );
};

export const TimeScaleTrack = memo(TimeScaleTrackView);
