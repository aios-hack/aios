import { memo, useCallback, useRef, type MouseEvent } from 'react';
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
  onSelect: (index: number) => void;
}

const TimeScaleTrackView = ({
  steps,
  stepIndex,
  ticks,
  marks,
  onSelect
}: TimeScaleTrackProps) => {
  const t = useT();
  const trackRef = useRef<HTMLDivElement | null>(null);
  const last = steps.length - 1;
  const terminal = steps.findIndex((step) => step.terminal);

  const onTrackClick = useCallback(
    (event: MouseEvent<HTMLDivElement>) => {
      const node = trackRef.current;
      if (node === null || last <= 0) {
        return;
      }
      const rect = node.getBoundingClientRect();
      if (rect.width === 0) {
        return;
      }
      const ratio = (event.clientX - rect.left) / rect.width;
      onSelect(Math.round(Math.min(Math.max(ratio, 0), 1) * last));
    },
    [last, onSelect]
  );

  return (
    <div
      ref={trackRef}
      className="time-scale-track"
      data-testid="time-scale-track"
      onClick={onTrackClick}
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
      <div className="time-scale-rail" aria-hidden="true">
        <span
          className="time-scale-fill"
          style={{ width: `${percentOf(stepIndex, last)}%` }}
        />
        {terminal >= 0 && (
          <span
            className="time-scale-terminal"
            data-testid="time-scale-terminal"
            style={{ left: `${percentOf(terminal, last)}%` }}
            title={t('steps.terminalBadge')}
          />
        )}
        <span
          className="time-scale-cursor"
          data-testid="time-scale-cursor"
          data-step={stepIndex}
          style={{ left: `${percentOf(stepIndex, last)}%` }}
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
            aria-label={t('steps.event', {
              date: steps[mark.step]?.date ?? '',
              count: mark.count
            })}
            title={t('steps.event', {
              date: steps[mark.step]?.date ?? '',
              count: mark.count
            })}
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
