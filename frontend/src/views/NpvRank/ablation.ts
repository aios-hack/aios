import type { AblationRule } from '../../api/types';

export type AblationState = 'measured' | 'zero' | 'unmeasured' | 'disabled';

export interface AblationEntry {
  rule: string;
  state: AblationState;
  delta: number | null;
  share: number | null;
  disabledReason: string | null;
}

export const stateOf = (rule: AblationRule): AblationState => {
  if (!rule.enabled) {
    return 'disabled';
  }
  if (rule.delta_npv === null) {
    return 'unmeasured';
  }
  return rule.delta_npv === 0 ? 'zero' : 'measured';
};

export const toEntry = (rule: AblationRule): AblationEntry => ({
  rule: rule.rule,
  state: stateOf(rule),
  delta: rule.delta_npv,
  share: rule.share,
  disabledReason: rule.disabled_reason ?? null
});

export const toEntries = (rules: readonly AblationRule[]): AblationEntry[] =>
  rules.map(toEntry);

export const barRatio = (share: number | null): number | null => {
  if (share === null) {
    return null;
  }
  return Math.min(Math.max(share, 0), 1);
};

export interface AblationCoverage {
  measured: number;
  unmeasured: number;
  accountedShare: number;
}

export const coverageOf = (entries: readonly AblationEntry[]): AblationCoverage => {
  let measured = 0;
  let unmeasured = 0;
  let accountedShare = 0;
  for (const entry of entries) {
    if (entry.share === null) {
      unmeasured += 1;
      continue;
    }
    measured += 1;
    accountedShare += entry.share;
  }
  return { measured, unmeasured, accountedShare };
};
