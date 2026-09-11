import { useT } from '@/shared/i18n/I18nContext';
import type { LegendNote, LegendRamp, LegendSwatch } from '@/shared/ui/Legend';
import { LegendPopover } from '@/shared/ui/Legend';
import { ViewToolbar } from '@/shared/ui/ViewToolbar';
import { HistorySegments } from '@/entities/timeline/ui/HistorySegments/HistorySegments';
import type { HistoryMetric, HistorySort } from '@/entities/timeline/model/historyControls';

interface ChronoControlsProps {
  metric: HistoryMetric;
  sort: HistorySort;
  onMetric: (metric: HistoryMetric) => void;
  onSort: (sort: HistorySort) => void;
  legendSwatches?: readonly LegendSwatch[];
  legendRamp?: LegendRamp;
  legendNotes: readonly LegendNote[];
}

export const ChronoControls = ({
  metric,
  sort,
  onMetric,
  onSort,
  legendSwatches,
  legendRamp,
  legendNotes
}: ChronoControlsProps) => {
  const t = useT();

  return (
    <ViewToolbar
      center={
        <HistorySegments
          metric={metric}
          onMetric={onMetric}
          metricEnabled
          sort={sort}
          onSort={onSort}
        />
      }
      right={
        <LegendPopover
          triggerLabel={t('toolbar.legend')}
          guide="history-matrix-legend"
          title={t('chrono.legend.title')}
          swatches={legendSwatches}
          ramp={legendRamp}
          notes={legendNotes}
        />
      }
    />
  );
};
