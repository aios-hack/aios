import { useT } from '../../i18n/I18nContext';
import { SegmentedControl, type SegmentedOption } from '../../ui/SegmentedControl';
import {
  HISTORY_METRICS,
  HISTORY_SORTS,
  type HistoryMetric,
  type HistorySort
} from './historyControls';

interface HistorySegmentsProps {
  metric: HistoryMetric;
  onMetric: (metric: HistoryMetric) => void;
  metricEnabled: boolean;
  sort: HistorySort;
  onSort: (sort: HistorySort) => void;
  sortDisabled?: readonly HistorySort[];
  sortGuide?: string;
}

export const HistorySegments = ({
  metric,
  onMetric,
  metricEnabled,
  sort,
  onSort,
  sortDisabled = [],
  sortGuide
}: HistorySegmentsProps) => {
  const t = useT();

  const metricOptions: SegmentedOption<HistoryMetric>[] = HISTORY_METRICS.map((value) => ({
    value,
    label: t(`history.metric.${value}`)
  }));

  const sortOptions: SegmentedOption<HistorySort>[] = HISTORY_SORTS.map((value) => ({
    value,
    label: t(`history.sort.${value}`),
    disabled: sortDisabled.includes(value),
    disabledReason: sortDisabled.includes(value)
      ? t('history.sortUnavailable')
      : undefined
  }));

  return (
    <>
      {metricEnabled && (
        <SegmentedControl<HistoryMetric>
          options={metricOptions}
          active={metric}
          label={t('history.metricLabel')}
          onSelect={onMetric}
        />
      )}
      <SegmentedControl<HistorySort>
        options={sortOptions}
        active={sort}
        label={t('history.sortLabel')}
        guide={sortGuide}
        onSelect={onSort}
      />
    </>
  );
};
