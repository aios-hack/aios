import {
  UNGROUPED,
  buildWellRows,
  groupByWell,
  sortWellRows,
  ungroupedCount,
  type WellRow
} from '@/entities/wells/model/wellFacts';
import { HISTORY_SORTS, type HistorySort } from '@/entities/timeline/model/historyControls';

export type ChronoSort = HistorySort;

export const CHRONO_SORTS: readonly ChronoSort[] = HISTORY_SORTS;

export type ChronoRow = WellRow;

export { UNGROUPED, groupByWell, ungroupedCount };

export const buildRows = buildWellRows;

export const sortRows = sortWellRows;
