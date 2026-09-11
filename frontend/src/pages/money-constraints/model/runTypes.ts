import type { RunManifest, RunSubmission } from '@/entities/runs/model/runTypes';
import type { ConstraintsDoc } from '@/entities/scenarios/types';

export interface UnseenYearly {
  absolute_error_pct: number | null;
}

export interface UnseenResult {
  focus_year: string;
  fitted_schedule_hashes_count: number;
  exact_fit_overlap: boolean;
  yearly: Record<string, Record<string, UnseenYearly>>;
  paired_comparison?: {
    predicted_npv_change_rub: number;
    opm_npv_change_rub: number;
  };
}

export interface RunValidation {
  dynamic_violations: number;
  blocking_dynamic_violations?: number;
  failed_identities: string[];
}

export interface LiveRun {
  run_id: string;
  status: string;
  mode: string;
  message: string;
  budget: number;
  evaluations?: number;
  feasible_evaluations?: number;
  rejection_reasons?: string[];
  manifest?: RunManifest;
  submission?: RunSubmission;
  flow_seconds?: number | null;
  unseen_result?: UnseenResult;
  constraints?: ConstraintsDoc;
  progress?: { step: number; total: number; date: string };
  economics?: { measured_npv?: number | null; sound?: boolean };
  provenance?: Partial<RunManifest>;
  validation?: RunValidation;
}

export const provenanceOf = (run: LiveRun): RunManifest | undefined => {
  if (run.manifest === undefined && run.provenance === undefined) {
    return undefined;
  }
  const merged: Record<string, unknown> = { ...run.provenance };
  for (const [key, value] of Object.entries(run.manifest ?? {})) {
    if (value !== null && value !== undefined) {
      merged[key] = value;
    }
  }
  return merged as RunManifest;
};

export const blockingViolationsOf = (run: LiveRun): number => {
  const validation = run.validation;
  if (validation === undefined) {
    return 0;
  }
  if (validation.blocking_dynamic_violations !== undefined) {
    return validation.blocking_dynamic_violations;
  }
  return run.manifest?.sound === true ? 0 : validation.dynamic_violations;
};
