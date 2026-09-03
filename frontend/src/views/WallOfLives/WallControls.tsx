import { useT } from '../../i18n/I18nContext';
import type { LegendNote, LegendSwatch } from '../../ui/Legend';
import { LegendPopover } from '../../ui/Legend';
import { ViewToolbar } from '../../ui/ViewToolbar';
import { HistorySegments } from '../shared/HistorySegments';
import type { HistoryMetric, HistorySort } from '../shared/historyControls';

interface WallControlsProps {
  metric: HistoryMetric;
  onMetric: (metric: HistoryMetric) => void;
  sort: HistorySort;
  onSort: (sort: HistorySort) => void;
  legendSwatches: readonly LegendSwatch[];
  legendNotes: readonly LegendNote[];
}

export const WallControls = ({
  metric,
  onMetric,
  sort,
  onSort,
  legendSwatches,
  legendNotes
}: WallControlsProps) => {
  const t = useT();

  return (
    <ViewToolbar
      center={
        <HistorySegments
          metric={metric}
          onMetric={onMetric}
          metricEnabled={false}
          sort={sort}
          onSort={onSort}
          sortGuide="history-wall-sort"
        />
      }
      right={
        <LegendPopover
          triggerLabel={t('toolbar.legend')}
          title={t('wall.legend.title')}
          swatches={legendSwatches}
          notes={legendNotes}
        />
      }
    />
  );
};
