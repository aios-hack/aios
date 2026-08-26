import type { ScenarioEntry } from '../../api/types';

export type TrustVerdictLevel = 'ok' | 'warn' | 'neutral';

export type TrustVerdictKind =
  | 'confirmed'
  | 'unconfirmedNumber'
  | 'outOfDomain'
  | 'notConverged'
  | 'missingField'
  | 'inDomain';

export interface TrustVerdict {
  kind: TrustVerdictKind;
  level: TrustVerdictLevel;
  labelKey: string;
  labelParams?: Record<string, string | number>;
}

const isMeasured = (value: number | null | undefined): value is number =>
  typeof value === 'number' && Number.isFinite(value);

const isFlag = (value: unknown): value is boolean => typeof value === 'boolean';

export const buildVerdict = (scenario: ScenarioEntry): TrustVerdict => {
  const final = scenario.final_npv;
  const hasFinalNpv = Boolean(final) && isMeasured(final?.npv_rub);
  if (hasFinalNpv) {
    if (scenario.run_validation_clean === true) {
      return {
        kind: 'confirmed',
        level: 'ok',
        labelKey: 'trust.chip.confirmed',
        labelParams: { run: (final as { run_id: string }).run_id }
      };
    }
    return { kind: 'unconfirmedNumber', level: 'warn', labelKey: 'trust.chip.unconfirmedNumber' };
  }

  const score = scenario.ood_score;
  const threshold = scenario.ood_threshold;
  const hasDomain = isMeasured(score) && isMeasured(threshold);
  if (hasDomain && (score as number) > (threshold as number)) {
    return { kind: 'outOfDomain', level: 'warn', labelKey: 'trust.chip.outOfDomain' };
  }

  const hasConverged = isFlag(scenario.converged);
  const hasSelfConsistent = isFlag(scenario.self_consistent);
  if (
    (hasConverged && scenario.converged === false) ||
    (hasSelfConsistent && scenario.self_consistent === false)
  ) {
    return { kind: 'notConverged', level: 'warn', labelKey: 'trust.chip.notConverged' };
  }

  if (!hasDomain) {
    return {
      kind: 'missingField',
      level: 'warn',
      labelKey: 'trust.chip.missingField',
      labelParams: { field: 'trust.label.domain' }
    };
  }

  if (!hasConverged) {
    return {
      kind: 'missingField',
      level: 'warn',
      labelKey: 'trust.chip.missingField',
      labelParams: { field: 'trust.label.converged' }
    };
  }

  if (!hasSelfConsistent) {
    return {
      kind: 'missingField',
      level: 'warn',
      labelKey: 'trust.chip.missingField',
      labelParams: { field: 'trust.label.selfConsistent' }
    };
  }

  return { kind: 'inDomain', level: 'neutral', labelKey: 'trust.chip.inDomain' };
};
