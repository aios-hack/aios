import { describe, expect, it } from 'vitest';
import type { AblationEntry } from './ablation';
import {
  ABLATION_SORT_KEYS,
  isNumericAblationKey,
  sortAblationEntries,
  type AblationLabels,
  type AblationSortKey
} from './ablationSorting';

const entry = (
  rule: string,
  delta: number | null,
  share: number | null = null
): AblationEntry => ({
  rule,
  state: delta === null ? 'unmeasured' : 'measured',
  delta,
  share,
  disabledReason: null
});

const LABELS: AblationLabels = {
  name: (rule) => `name-${rule}`,
  statement: (rule) => `statement-${rule}`
};

const rules = (entries: readonly AblationEntry[]): string[] =>
  entries.map((item) => item.rule);

describe('ablation sort keys', () => {
  it('offers a key for every column the table renders', () => {
    expect(ABLATION_SORT_KEYS).toHaveLength(5);
    expect(new Set(ABLATION_SORT_KEYS).size).toBe(5);
  });

  it('marks exactly the measured columns as numeric', () => {
    const numeric = ABLATION_SORT_KEYS.filter((key: AblationSortKey) =>
      isNumericAblationKey(key)
    );
    expect(numeric).toEqual(['delta', 'share']);
  });
});

describe('sortAblationEntries', () => {
  const mixed: AblationEntry[] = [
    entry('R3', null),
    entry('R1', 40, 0.4),
    entry('R2', null),
    entry('R4', 10, 0.1)
  ];

  it('sorts measured rules by delta ascending', () => {
    expect(rules(sortAblationEntries(mixed, 'delta', 'asc', LABELS)).slice(0, 2)).toEqual([
      'R4',
      'R1'
    ]);
  });

  it('sorts measured rules by delta descending', () => {
    expect(rules(sortAblationEntries(mixed, 'delta', 'desc', LABELS)).slice(0, 2)).toEqual([
      'R1',
      'R4'
    ]);
  });

  it('keeps unmeasured rules last whichever way the column points', () => {
    expect(rules(sortAblationEntries(mixed, 'delta', 'asc', LABELS))).toEqual([
      'R4',
      'R1',
      'R2',
      'R3'
    ]);
    expect(rules(sortAblationEntries(mixed, 'delta', 'desc', LABELS))).toEqual([
      'R1',
      'R4',
      'R2',
      'R3'
    ]);
  });

  it('keeps unmeasured rules last when sorting by a text column too', () => {
    const byName = rules(sortAblationEntries(mixed, 'name', 'desc', LABELS));
    expect(byName.slice(2)).toEqual(['R2', 'R3']);
  });

  it('orders unmeasured rules among themselves by rule code, never reversed', () => {
    const unmeasured = [entry('R9', null), entry('R2', null), entry('R5', null)];
    expect(rules(sortAblationEntries(unmeasured, 'delta', 'asc', LABELS))).toEqual([
      'R2',
      'R5',
      'R9'
    ]);
    expect(rules(sortAblationEntries(unmeasured, 'delta', 'desc', LABELS))).toEqual([
      'R2',
      'R5',
      'R9'
    ]);
    expect(rules(sortAblationEntries(unmeasured, 'share', 'desc', LABELS))).toEqual([
      'R2',
      'R5',
      'R9'
    ]);
  });

  it('breaks ties on equal deltas by rule code so the order never wobbles', () => {
    const tied = [entry('R7', 5, 0.5), entry('R2', 5, 0.5), entry('R4', 5, 0.5)];
    expect(rules(sortAblationEntries(tied, 'delta', 'asc', LABELS))).toEqual([
      'R2',
      'R4',
      'R7'
    ]);
  });

  it('sorts by share independently of delta', () => {
    const entries = [entry('R1', 100, 0.1), entry('R2', 10, 0.9)];
    expect(rules(sortAblationEntries(entries, 'share', 'asc', LABELS))).toEqual([
      'R1',
      'R2'
    ]);
    expect(rules(sortAblationEntries(entries, 'delta', 'asc', LABELS))).toEqual([
      'R2',
      'R1'
    ]);
  });

  it('sorts by the rendered label, not by the rule code', () => {
    const labels: AblationLabels = {
      name: (rule) => (rule === 'R1' ? 'zeta' : 'alpha'),
      statement: (rule) => rule
    };
    const entries = [entry('R1', 1, 0.1), entry('R2', 2, 0.2)];
    expect(rules(sortAblationEntries(entries, 'name', 'asc', labels))).toEqual([
      'R2',
      'R1'
    ]);
  });

  it('pushes rules with an empty label to the end of a text sort', () => {
    const labels: AblationLabels = {
      name: (rule) => (rule === 'R1' ? '' : 'alpha'),
      statement: (rule) => rule
    };
    const entries = [entry('R1', 1, 0.1), entry('R2', 2, 0.2)];
    expect(rules(sortAblationEntries(entries, 'name', 'asc', labels))).toEqual([
      'R2',
      'R1'
    ]);
  });

  it('never mutates the entries it was given', () => {
    const original = rules(mixed);
    sortAblationEntries(mixed, 'delta', 'desc', LABELS);
    expect(rules(mixed)).toEqual(original);
  });

  it('handles an empty table', () => {
    expect(sortAblationEntries([], 'delta', 'asc', LABELS)).toEqual([]);
  });

  it('treats a rule measured at zero as measured, not as missing', () => {
    const entries = [entry('R1', null), entry('R2', 0, 0)];
    expect(rules(sortAblationEntries(entries, 'delta', 'asc', LABELS))).toEqual([
      'R2',
      'R1'
    ]);
    expect(rules(sortAblationEntries(entries, 'delta', 'desc', LABELS))).toEqual([
      'R2',
      'R1'
    ]);
  });
});
