import {
  UNGROUPED,
  buildWellRows,
  sortWellRows,
  type WellRow
} from '@/entities/wells/model/wellFacts';
import { HISTORY_SORTS, type HistorySort } from '@/entities/timeline/model/historyControls';

export type WallSort = HistorySort;

export const WALL_SORTS: readonly WallSort[] = HISTORY_SORTS;

export type WallRow = WellRow;

export const buildWallRows = buildWellRows;

export const sortWallRows = sortWellRows;

export const ungroupedWells = (rows: readonly WallRow[]): string[] =>
  rows.filter((row) => row.group === UNGROUPED).map((row) => row.well);
