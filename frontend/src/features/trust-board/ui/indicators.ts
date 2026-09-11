import type { ScenarioEntry } from '@/entities/scenarios/types';

export type TrustStatus = 'neutral' | 'danger' | 'unmeasured';

export type TrustIndicatorId =
  | 'converged'
  | 'selfConsistent'
  | 'domain'
  | 'regret'
  | 'number'
  | 'physics'
  | 'provenance';

export interface TrustIndicator {
  id: TrustIndicatorId;
  status: TrustStatus;
  labelKey: string;
  valueKey: string;
  valueParams?: Record<string, string | number>;
  detailKey?: string;
  detailParams?: Record<string, string | number>;
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

const physicsIndicator = (scenario: ScenarioEntry): TrustIndicator => {
  const physics = scenario.physics;
  if (!physics || !isMeasured(physics.total) || !isMeasured(physics.evaluated_count)) {
    return unmeasured('physics', 'trust.label.physics');
  }
  const { evaluated_count: done, total } = physics;
  const skipped = physics.skipped ?? [];
  const missing = skipped
    .map((item) => item.invariant)
    .join(', ');
  const counted = { done, total };
  if (!physics.complete) {
    return {
      id: 'physics',
      status: 'unmeasured',
      labelKey: 'trust.label.physics',
      valueKey: 'trust.physics.partial',
      valueParams: counted,
      briefKey: 'trust.physics.counted',
      briefParams: counted,
      detailKey: missing.length > 0 ? 'trust.physics.skipped' : undefined,
      detailParams: missing.length > 0 ? { invariants: missing } : undefined,
      spoken: true
    };
  }
  const blocking = isMeasured(physics.blocking_count) ? physics.blocking_count : 0;
  const warnings = isMeasured(physics.warning_count) ? physics.warning_count : 0;
  if (blocking > 0) {
    return {
      id: 'physics',
      status: 'danger',
      labelKey: 'trust.label.physics',
      valueKey: 'trust.physics.blocking',
      valueParams: { count: blocking },
      briefKey: 'trust.physics.counted',
      briefParams: counted,
      spoken: true
    };
  }
  return {
    id: 'physics',
    status: 'neutral',
    labelKey: 'trust.label.physics',
    valueKey: 'trust.physics.clean',
    valueParams: counted,
    briefKey: 'trust.physics.counted',
    briefParams: counted,
    detailKey: warnings > 0 ? 'trust.physics.warnings' : undefined,
    detailParams: warnings > 0 ? { count: warnings } : undefined
  };
};

const SYNTHETIC_PROVENANCE = /^(synthetic|demo|mock|sample|fixture)/i;

export const isSyntheticProvenance = (provenance: string): boolean =>
  SYNTHETIC_PROVENANCE.test(provenance.trim());

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
  if (isSyntheticProvenance(source.provenance)) {
    return {
      id: 'provenance',
      status: 'unmeasured',
      labelKey: 'trust.label.provenance',
      valueKey: 'trust.provenance.synthetic',
      briefKey: 'trust.brief.synthetic',
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
  physicsIndicator(scenario),
  provenanceIndicator(source)
];
