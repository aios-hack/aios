import {
  UNGROUPED,
  buildWellRows,
  groupByWell,
  sortWellRows,
  ungroupedCount,
  type WellRow
} from '../shared/wellFacts';
import { HISTORY_SORTS, type HistorySort } from '../shared/historyControls';

export type ChronoSort = HistorySort;

export const CHRONO_SORTS: readonly ChronoSort[] = HISTORY_SORTS;

export type ChronoRow = WellRow;

export { UNGROUPED, groupByWell, ungroupedCount };

export const buildRows = buildWellRows;

export const sortRows = sortWellRows;
