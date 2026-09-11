import type { ArtifactMeta } from '@/shared/api/artifact';

export interface WellOutageDoc {
  well: string;
  control_step_from: number;
  control_step_to: number;
}

export interface ConstraintsDoc {
  injection_limits: Record<string, number>;
  liquid_limits: Record<string, number>;
  production_floors: Record<string, number>;
  watercut_limits: Record<string, number>;
  well_outages: WellOutageDoc[];
  infrastructure: Record<string, string | number>;
}

export interface ScenarioConstraintsSummary {
  injection_limits: number;
  liquid_limits: number;
  production_floors: number;
  watercut_limits: number;
  well_outages: number;
  infrastructure: number;
  years: number[];
  outage_wells: string[];
  empty: boolean;
}

export type RegretPart = 'optimization' | 'holdout';

export interface ScenarioWorstRegret {
  scenario_id: string;
  value_rub: number;
  part: RegretPart;
}

export interface ScenarioFinalNpv {
  npv_rub: number;
  run_id: string;
}

export interface ScenarioPhysicsSkip {
  invariant: string;
  reason: string;
  severity: string;
}

export interface ScenarioPhysics {
  total: number;
  evaluated_count: number;
  evaluated: string[];
  skipped: ScenarioPhysicsSkip[];
  blocking_count: number;
  warning_count: number;
  complete: boolean;
  admissible: boolean;
  warning_invariants: string[];
}

export interface ScenarioEntry {
  id: string;
  config_hash: string;
  converged: boolean;
  self_consistent: boolean;
  is_submitted: boolean;
  npv_methodology: number | null;
  constraints: ScenarioConstraintsSummary;
  ood_score?: number | null;
  ood_threshold?: number | null;
  worst_regret?: ScenarioWorstRegret | null;
  final_npv?: ScenarioFinalNpv | null;
  predicted_npv_rub?: number | null;
  calibrated_npv_rub?: number | null;
  run_validation_clean?: boolean | null;
  physics?: ScenarioPhysics | null;
}

export interface ScenariosFile {
  meta?: ArtifactMeta;
  scenarios: ScenarioEntry[];
  submitted: string | null;
}
