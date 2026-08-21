import { ViewToolbar } from '../../ui/ViewToolbar';
import { HistorySegments } from '../shared/HistorySegments';
import type { HistoryMetric, HistorySort } from '../shared/historyControls';

interface HistoryTableControlsProps {
  metric: HistoryMetric;
  onMetric: (metric: HistoryMetric) => void;
  sort: HistorySort;
  onSort: (sort: HistorySort) => void;
}

export const HistoryTableControls = ({
  metric,
  onMetric,
  sort,
  onSort
}: HistoryTableControlsProps) => (
  <ViewToolbar
    center={
      <HistorySegments
        metric={metric}
        onMetric={onMetric}
        metricEnabled={false}
        sort={sort}
        onSort={onSort}
      />
    }
  />
);
