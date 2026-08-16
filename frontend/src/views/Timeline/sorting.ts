import type { TimelineWellRow } from '../../api/types';

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

export const actualRate = (row: TimelineWellRow): number =>
  row.role === 'INJ' ? row.injection_rate : row.liquid_rate;

const isCommissioned = (row: TimelineWellRow): boolean =>
  row.availability !== 'NOT_COMMISSIONED';

const wellOrder = (well: string): [number, string] => {
  const numeric = Number(well);
  return Number.isFinite(numeric) ? [numeric, ''] : [Number.POSITIVE_INFINITY, well];
};

const compareWell = (a: TimelineWellRow, b: TimelineWellRow): number => {
  const [numA, textA] = wellOrder(a.well);
  const [numB, textB] = wellOrder(b.well);
  return numA === numB ? textA.localeCompare(textB) : numA - numB;
};

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

const compareBy = (a: TimelineWellRow, b: TimelineWellRow, key: SortKey): number => {
  if (key === 'well') {
    return compareWell(a, b);
  }
  if (!isNumericKey(key)) {
    const diff = textOf(a, key).localeCompare(textOf(b, key));
    return diff === 0 ? compareWell(a, b) : diff;
  }
  const left = numberOf(a, key);
  const right = numberOf(b, key);
  if (left === null && right === null) {
    return compareWell(a, b);
  }
  if (left === null) {
    return 1;
  }
  if (right === null) {
    return -1;
  }
  return left === right ? compareWell(a, b) : left - right;
};

export const sortWells = (
  wells: readonly TimelineWellRow[],
  key: SortKey,
  dir: SortDir
): TimelineWellRow[] => {
  const rows = [...wells];
  rows.sort((a, b) => {
    const diff = compareBy(a, b, key);
    return dir === 'asc' ? diff : -diff;
  });
  return rows;
};
