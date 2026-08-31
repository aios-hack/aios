import type { TimelineWellRow } from '../../api/types';
import type { Lang } from '../../i18n/dictionaries';
import { formatNumber, formatPercent } from '../../ui/format';
import { modeOf, type ChronoMetric } from './cells';

interface ReadingContext {
  lang: Lang;
  t: (key: string) => string;
  metric: ChronoMetric;
  row: TimelineWellRow | undefined;
  npv?: number;
}

export const readingText = ({ lang, t, metric, row, npv }: ReadingContext): string => {
  if (metric === 'npv') {
    return npv === undefined ? t('chrono.value.unknown') : formatNumber(lang, npv);
  }
  if (row === undefined) {
    return t('chrono.value.unknown');
  }
  if (metric === 'mode') {
    return t(`chrono.mode.${modeOf(row)}`);
  }
  if (row.availability === 'NOT_COMMISSIONED') {
    return t('chrono.value.unknown');
  }
  const raw = metric === 'watercut' ? row.watercut : row.fact_to_target;
  if (raw === null || !Number.isFinite(raw)) {
    return t('chrono.value.unknown');
  }
  return formatPercent(lang, raw);
};
