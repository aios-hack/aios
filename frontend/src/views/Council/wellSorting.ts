import { compareWellIds } from '../../ui/format/wellOrder';
import type { WellRow } from './levels';

export type SortDir = 'asc' | 'desc';

export type WellSortKey =
  | 'well'
  | 'decision'
  | 'amount'
  | 'rule'
  | 'groupLimit'
  | 'injection'
  | 'liquid'
  | 'constraint';

export const WELL_SORT_KEYS: readonly WellSortKey[] = [
  'well',
  'decision',
  'amount',
  'rule',
  'groupLimit',
  'injection',
  'liquid',
  'constraint'
];

const NUMERIC_KEYS: readonly WellSortKey[] = [
  'amount',
  'groupLimit',
  'injection',
  'liquid'
];

export const isNumericWellKey = (key: WellSortKey): boolean =>
  NUMERIC_KEYS.includes(key);

const DECISION = /^(\S+)\s+(-?[\d.]+)$/;

export const decisionVerb = (decision: string): string =>
  DECISION.exec(decision)?.[1] ?? decision;

export const decisionAmount = (decision: string): number | null => {
  const parsed = DECISION.exec(decision)?.[2];
  if (parsed === undefined) {
    return null;
  }
  const value = Number(parsed);
  return Number.isFinite(value) ? value : null;
};

const numberOf = (row: WellRow, key: WellSortKey): number | null => {
  if (key === 'amount') {
    return decisionAmount(row.decision);
  }
  const inputs = row.inputs;
  if (key === 'groupLimit') {
    return inputs.group_limit_m3_per_day ?? null;
  }
  if (key === 'injection') {
    return inputs.injection_rate_m3_per_day ?? null;
  }
  return inputs.liquid_rate_m3_per_day ?? null;
};

const textOf = (row: WellRow, key: WellSortKey): string => {
  if (key === 'decision') {
    return decisionVerb(row.decision);
  }
  if (key === 'rule') {
    return row.rule;
  }
  return row.constraint ?? '';
};

const compareBy = (a: WellRow, b: WellRow, key: WellSortKey): number => {
  if (key === 'well') {
    return compareWellIds(a.well, b.well);
  }
  if (!isNumericWellKey(key)) {
    const left = textOf(a, key);
    const right = textOf(b, key);
    if (left === right) {
      return compareWellIds(a.well, b.well);
    }
    if (left === '') {
      return 1;
    }
    if (right === '') {
      return -1;
    }
    return left.localeCompare(right);
  }
  const left = numberOf(a, key);
  const right = numberOf(b, key);
  if (left === null && right === null) {
    return compareWellIds(a.well, b.well);
  }
  if (left === null) {
    return 1;
  }
  if (right === null) {
    return -1;
  }
  return left === right ? compareWellIds(a.well, b.well) : left - right;
};

export const sortWellRows = (
  rows: readonly WellRow[],
  key: WellSortKey,
  dir: SortDir
): WellRow[] => {
  const sorted = [...rows];
  sorted.sort((a, b) => {
    const diff = compareBy(a, b, key);
    return dir === 'asc' ? diff : -diff;
  });
  return sorted;
};
