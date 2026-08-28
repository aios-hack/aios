import type { TimelineStep, TimelineWellRow } from '../../api/types';
import { useI18n } from '../../i18n/I18nContext';
import { DASH, formatStepDate } from '../../ui/format';
import type { ChronoMetric } from './cells';
import { readingText } from './readings';

export interface HoverTarget {
  well: string;
  column: number;
  x: number;
  y: number;
}

interface ChronoTooltipProps {
  target: HoverTarget;
  step: TimelineStep | undefined;
  row: TimelineWellRow | undefined;
  metric: ChronoMetric;
  npv: number | undefined;
}

export const ChronoTooltip = ({
  target,
  step,
  row,
  metric,
  npv
}: ChronoTooltipProps) => {
  const { t, lang } = useI18n();

  const valueText = (): string => readingText({ lang, t, metric, row, npv });

  return (
    <div
      className="chronomap-tooltip"
      role="tooltip"
      style={{ left: `${target.x}px`, top: `${target.y}px` }}
    >
      <span className="chronomap-tooltip-well">{target.well}</span>
      <span className="chronomap-tooltip-date">
        {step === undefined ? DASH : formatStepDate(lang, step.date)}
      </span>
      <span className="chronomap-tooltip-value">
        {t(`chrono.value.${metric}`, { value: valueText() })}
      </span>
      {step?.terminal === true && (
        <span className="chronomap-tooltip-terminal">{t('chrono.terminalNote')}</span>
      )}
    </div>
  );
};
