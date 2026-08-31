import type { ScenarioEntry } from '../../api/types';

export type TrustStatus = 'neutral' | 'danger' | 'unmeasured';

export type TrustIndicatorId =
  | 'converged'
  | 'selfConsistent'
  | 'domain'
  | 'regret'
  | 'number'
  | 'provenance';

export interface TrustIndicator {
  id: TrustIndicatorId;
  status: TrustStatus;
  labelKey: string;
  valueKey: string;
  valueParams?: Record<string, string | number>;
  detailKey?: string;
  detailParams?: Record<string, string | number>;
  banner?: boolean;
  briefKey?: string;
  briefParams?: Record<string, string | number>;
  spoken?: boolean;
}

export interface TrustProvenance {
  provenance: string;
}

const isMeasured = (value: number | null | undefined): value is number =>
  typeof value === 'number' && Number.isFinite(value);

const unmeasured = (
  id: TrustIndicatorId,
  labelKey: string
): TrustIndicator => ({
  id,
  status: 'unmeasured',
  labelKey,
  valueKey: 'trust.unmeasured',
  spoken: true
});

const flagIndicator = (
  id: TrustIndicatorId,
  labelKey: string,
  namespace: string,
  flag: unknown
): TrustIndicator => {
  if (typeof flag !== 'boolean') {
    return unmeasured(id, labelKey);
  }
  return {
    id,
    status: flag ? 'neutral' : 'danger',
    labelKey,
    valueKey: `trust.${namespace}.${flag ? 'yes' : 'no'}`,
    briefKey: `trust.brief.${flag ? 'yes' : 'no'}`,
    spoken: !flag
  };
};

const domainIndicator = (scenario: ScenarioEntry): TrustIndicator => {
  const score = scenario.ood_score;
  const threshold = scenario.ood_threshold;
  if (!isMeasured(score) || !isMeasured(threshold)) {
    return unmeasured('domain', 'trust.label.domain');
  }
  const outside = score > threshold;
  return {
    id: 'domain',
    status: outside ? 'danger' : 'neutral',
    labelKey: 'trust.label.domain',
    valueKey: outside ? 'trust.domain.outside' : 'trust.domain.inside',
    briefKey: outside ? 'trust.brief.outside' : 'trust.brief.inside',
    spoken: outside,
    detailKey: 'trust.domain.detail',
    detailParams: { score, threshold }
  };
};

const regretIndicator = (scenario: ScenarioEntry): TrustIndicator => {
  const regret = scenario.worst_regret;
  if (!regret || !isMeasured(regret.value_rub)) {
    return unmeasured('regret', 'trust.label.regret');
  }
  return {
    id: 'regret',
    status: 'neutral',
    labelKey: 'trust.label.regret',
    valueKey: 'trust.regret.worst',
    valueParams: { value: regret.value_rub, scenario: regret.scenario_id },
    briefKey: 'trust.brief.regret',
    briefParams: { value: regret.value_rub },
    detailKey: `trust.regret.part.${regret.part}`
  };
};

const numberIndicator = (scenario: ScenarioEntry): TrustIndicator => {
  const final = scenario.final_npv;
  if (!final || !isMeasured(final.npv_rub)) {
    if (isMeasured(scenario.predicted_npv_rub)) {
      return {
        id: 'number',
        status: 'unmeasured',
        labelKey: 'trust.label.number',
        valueKey: 'trust.number.forecastValue',
        valueParams: { value: scenario.predicted_npv_rub },
        briefKey: 'trust.number.forecast',
        spoken: true
      };
    }
    return {
      id: 'number',
      status: 'unmeasured',
      labelKey: 'trust.label.number',
      valueKey: 'trust.number.forecast',
      spoken: true
    };
  }
  return {
    id: 'number',
    status: 'neutral',
    labelKey: 'trust.label.number',
    valueKey: 'trust.number.confirmed',
    valueParams: { run: final.run_id },
    briefKey: 'trust.brief.confirmed',
    detailKey: isMeasured(scenario.predicted_npv_rub)
      ? isMeasured(scenario.calibrated_npv_rub)
        ? 'trust.number.confirmedCalibratedComparison'
        : 'trust.number.confirmedComparison'
      : 'trust.number.confirmedValue',
    detailParams: isMeasured(scenario.predicted_npv_rub)
      ? isMeasured(scenario.calibrated_npv_rub)
        ? {
            value: final.npv_rub,
            calibrated: scenario.calibrated_npv_rub,
            predicted: scenario.predicted_npv_rub
          }
        : { value: final.npv_rub, predicted: scenario.predicted_npv_rub }
      : { value: final.npv_rub }
  };
};

const provenanceIndicator = (source: TrustProvenance): TrustIndicator => {
  if (source.provenance.length === 0) {
    return {
      id: 'provenance',
      status: 'unmeasured',
      labelKey: 'trust.label.provenance',
      valueKey: 'trust.provenance.unknown',
      spoken: true
    };
  }
  return {
    id: 'provenance',
    status: 'neutral',
    labelKey: 'trust.label.provenance',
    valueKey: 'trust.provenance.measured',
    briefKey: 'trust.brief.measured'
  };
};

export const buildIndicators = (
  scenario: ScenarioEntry,
  source: TrustProvenance
): TrustIndicator[] => [
  flagIndicator('converged', 'trust.label.converged', 'converged', scenario.converged),
  flagIndicator(
    'selfConsistent',
    'trust.label.selfConsistent',
    'selfConsistent',
    scenario.self_consistent
  ),
  domainIndicator(scenario),
  regretIndicator(scenario),
  numberIndicator(scenario),
  provenanceIndicator(source)
];
