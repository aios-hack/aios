import type { AblationEntry } from './ablation';

export type AblationSortDir = 'asc' | 'desc';

export type AblationSortKey = 'rule' | 'name' | 'statement' | 'delta' | 'share';

export const ABLATION_SORT_KEYS: readonly AblationSortKey[] = [
  'rule',
  'name',
  'statement',
  'delta',
  'share'
];

const NUMERIC_KEYS: readonly AblationSortKey[] = ['delta', 'share'];

export const isNumericAblationKey = (key: AblationSortKey): boolean =>
  NUMERIC_KEYS.includes(key);

export interface AblationLabels {
  name: (rule: string) => string;
  statement: (rule: string) => string;
}

const textOf = (
  entry: AblationEntry,
  key: AblationSortKey,
  labels: AblationLabels
): string => {
  if (key === 'name') {
    return labels.name(entry.rule);
  }
  if (key === 'statement') {
    return labels.statement(entry.rule);
  }
  return entry.rule;
};

const numberOf = (entry: AblationEntry, key: AblationSortKey): number | null =>
  key === 'delta' ? entry.delta : entry.share;

const compareBy = (
  a: AblationEntry,
  b: AblationEntry,
  key: AblationSortKey,
  labels: AblationLabels
): number => {
  if (!isNumericAblationKey(key)) {
    const left = textOf(a, key, labels);
    const right = textOf(b, key, labels);
    if (left === right) {
      return a.rule.localeCompare(b.rule);
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
    return a.rule.localeCompare(b.rule);
  }
  if (left === null) {
    return 1;
  }
  if (right === null) {
    return -1;
  }
  return left === right ? a.rule.localeCompare(b.rule) : left - right;
};

export const sortAblationEntries = (
  entries: readonly AblationEntry[],
  key: AblationSortKey,
  dir: AblationSortDir,
  labels: AblationLabels
): AblationEntry[] => {
  const sorted = [...entries];
  sorted.sort((a, b) => {
    const unmeasuredGap = Number(a.delta === null) - Number(b.delta === null);
    if (unmeasuredGap !== 0) {
      return unmeasuredGap;
    }
    if (a.delta === null && b.delta === null) {
      return compareBy(a, b, isNumericAblationKey(key) ? 'rule' : key, labels);
    }
    const diff = compareBy(a, b, key, labels);
    return dir === 'asc' ? diff : -diff;
  });
  return sorted;
};
