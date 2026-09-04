import type { ArtifactMeta, ScenarioEntry } from '../../api/types';

export type NpvProvenanceKind = 'run' | 'forecast' | 'methodology' | 'unmeasured';

export interface NpvProvenance {
  kind: NpvProvenanceKind;
  labelKey: string;
  params?: Record<string, string | number>;
  noteKey?: string;
  noteParams?: Record<string, string | number>;
  synthetic: boolean;
}

export type ArtifactProvenance = (ArtifactMeta & { synthetic?: boolean }) | undefined;

const SYNTHETIC_PROVENANCE = /^(synthetic|demo|mock|sample|fixture)/i;

export const isSyntheticArtifact = (meta: ArtifactProvenance): boolean => {
  if (meta === undefined) {
    return false;
  }
  if (meta.synthetic === true) {
    return true;
  }
  return SYNTHETIC_PROVENANCE.test((meta.provenance ?? '').trim());
};

const isMeasured = (value: number | null | undefined): value is number =>
  typeof value === 'number' && Number.isFinite(value);

export const npvProvenanceOf = (
  scenario: ScenarioEntry | undefined,
  meta: ArtifactProvenance
): NpvProvenance => {
  const synthetic = isSyntheticArtifact(meta);

  if (scenario === undefined) {
    return { kind: 'unmeasured', labelKey: 'npv.provenance.unmeasured', synthetic };
  }

  const final = scenario.final_npv;
  if (final && isMeasured(final.npv_rub) && scenario.run_validation_clean === true) {
    return {
      kind: 'run',
      labelKey: 'npv.provenance.run',
      params: { run: final.run_id },
      noteKey: isMeasured(scenario.predicted_npv_rub)
        ? 'npv.provenance.runVersusForecast'
        : undefined,
      noteParams: isMeasured(scenario.predicted_npv_rub)
        ? { predicted: scenario.predicted_npv_rub }
        : undefined,
      synthetic
    };
  }

  if (final && isMeasured(final.npv_rub)) {
    return {
      kind: 'unmeasured',
      labelKey: 'npv.provenance.runDirty',
      params: { run: final.run_id },
      synthetic
    };
  }

  if (isMeasured(scenario.predicted_npv_rub)) {
    return {
      kind: 'forecast',
      labelKey: 'npv.provenance.forecast',
      noteKey:
        isMeasured(scenario.ood_score) && isMeasured(scenario.ood_threshold)
          ? scenario.ood_score > scenario.ood_threshold
            ? 'npv.provenance.forecastOutside'
            : 'npv.provenance.forecastInside'
          : undefined,
      noteParams:
        isMeasured(scenario.ood_score) && isMeasured(scenario.ood_threshold)
          ? { score: scenario.ood_score, threshold: scenario.ood_threshold }
          : undefined,
      synthetic
    };
  }

  if (isMeasured(scenario.npv_methodology)) {
    return { kind: 'methodology', labelKey: 'npv.provenance.methodology', synthetic };
  }

  return { kind: 'unmeasured', labelKey: 'npv.provenance.unmeasured', synthetic };
};
