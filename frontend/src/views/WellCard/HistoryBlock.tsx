import type { TimelineFile } from '../../api/types';
import { useI18n } from '../../i18n/I18nContext';
import { Sparkline } from '../../ui/Sparkline';
import { DASH, formatNumber, formatPercent } from '../../ui/format';
import { buildWellSeries, type WellSeriesKey } from './wellSeries';

interface HistoryBlockProps {
  timeline: TimelineFile;
  well: string;
  stepIndex: number;
}

const STROKE: Record<WellSeriesKey, string> = {
  rate: 'var(--color-oil)',
  watercut: 'var(--color-water)',
  bhp: 'var(--color-text-muted)'
};

const INJECTOR_STROKE = 'var(--color-injection)';

export const HistoryBlock = ({ timeline, well, stepIndex }: HistoryBlockProps) => {
  const { t, lang } = useI18n();
  const series = buildWellSeries(timeline, well);

  if (series.length === 0) {
    return null;
  }

  return (
    <section className="wellcard-section">
      <h4 className="wellcard-section-title">{t('wellcard.history.title')}</h4>
      {series.map((row) => {
        const current = row.values[stepIndex] ?? null;
        const label =
          row.key === 'rate' && row.injector
            ? t('wellcard.history.injection')
            : t(`wellcard.history.${row.key}`);
        const reading =
          current === null
            ? DASH
            : row.key === 'watercut'
              ? formatPercent(lang, current)
              : formatNumber(lang, current);
        return (
          <div className="wellcard-history-row" key={row.key} data-series={row.key}>
            <span className="wellcard-history-label">{label}</span>
            <Sparkline
              values={row.values}
              current={stepIndex}
              total={timeline.steps.length}
              label={label}
              height={26}
              stroke={row.key === 'rate' && row.injector ? INJECTOR_STROKE : STROKE[row.key]}
            />
            <span className="wellcard-history-value" data-empty={current === null}>
              {reading}
            </span>
          </div>
        );
      })}
    </section>
  );
};
