import type { TimelineStep, TimelineWellRow } from '../../api/types';
import { useI18n } from '../../i18n/I18nContext';
import { DASH, formatNumber, formatPercent, formatStepDate } from '../../ui/format';
import { modeOf, type ChronoMetric } from './cells';

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

  const valueText = (): string => {
    if (metric === 'npv') {
      return npv === undefined ? t('chrono.value.unknown') : formatNumber(lang, npv);
    }
    if (row === undefined) {
      return t('chrono.value.unknown');
    }
    if (metric === 'mode') {
      return t(`chrono.mode.${modeOf(row)}`);
    }
    const raw = metric === 'watercut' ? row.watercut : row.fact_to_target;
    if (raw === null || Number.isNaN(raw)) {
      return t('chrono.value.unknown');
    }
    return formatPercent(lang, raw);
  };

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
