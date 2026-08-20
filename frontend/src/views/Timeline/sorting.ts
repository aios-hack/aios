import type { TimelineWellRow } from '../../api/types';
import { actualRate, isCommissioned } from '../../data';
import { compareWellIds } from '../../ui/format';

export type SortDir = 'asc' | 'desc';

export type SortKey =
  | 'well'
  | 'availability'
  | 'role'
  | 'status'
  | 'setpoint'
  | 'actual'
  | 'watercut'
  | 'bhp';

export const SORT_KEYS: readonly SortKey[] = [
  'well',
  'availability',
  'role',
  'status',
  'setpoint',
  'actual',
  'watercut',
  'bhp'
];

const compareWell = (a: TimelineWellRow, b: TimelineWellRow): number =>
  compareWellIds(a.well, b.well);

const textOf = (row: TimelineWellRow, key: SortKey): string => {
  if (key === 'availability') {
    return row.availability;
  }
  if (key === 'role') {
    return row.role;
  }
  return row.operating_status;
};

const numberOf = (row: TimelineWellRow, key: SortKey): number | null => {
  if (!isCommissioned(row)) {
    return null;
  }
  if (key === 'setpoint') {
    return row.setpoint;
  }
  if (key === 'actual') {
    return actualRate(row);
  }
  if (key === 'watercut') {
    return row.watercut;
  }
  return row.bhp;
};

const NUMERIC_KEYS: readonly SortKey[] = ['setpoint', 'actual', 'watercut', 'bhp'];

export const isNumericKey = (key: SortKey): boolean => NUMERIC_KEYS.includes(key);

export const sortWells = (
  wells: readonly TimelineWellRow[],
  key: SortKey,
  dir: SortDir
): TimelineWellRow[] => {
  const rows = [...wells];
  rows.sort((a, b) => {
    if (key === 'well') {
      const diff = compareWell(a, b);
      return dir === 'asc' ? diff : -diff;
    }
    if (isNumericKey(key)) {
      const left = numberOf(a, key);
      const right = numberOf(b, key);
      if (left === null || right === null) {
        return left === right ? compareWell(a, b) : left === null ? 1 : -1;
      }
      return left === right ? compareWell(a, b) : dir === 'asc' ? left - right : right - left;
    }
    const diff = textOf(a, key).localeCompare(textOf(b, key));
    if (diff === 0) {
      return compareWell(a, b);
    }
    return dir === 'asc' ? diff : -diff;
  });
  return rows;
};
