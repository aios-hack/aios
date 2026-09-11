export interface RunManifest {
  run_id: string;
  status: string;
  predicted_npv?: number;
  verified_npv?: number;
  sound?: boolean;
  schedule_hash?: string;
}

export interface RunProvenance {
  opm_image?: string;
  deck_hash?: string;
  case_hash?: string;
  git_commit?: string;
}

export interface RunRow {
  run_id: string;
  created_at?: string;
  status: string;
  mode?: string;
  message?: string;
  budget?: number;
  manifest?: RunManifest;
  provenance?: RunProvenance;
  evaluations?: number;
  feasible_evaluations?: number;
}

export interface RunsResponse {
  runs: RunRow[];
}

export interface ComparisonRowFile {
  metric: string;
  baseline: string;
  candidate: string;
  delta: string;
}

export interface ComparisonViolations {
  static: number | null;
  dynamic: number | null;
  blocking: number | null;
}

export interface ComparisonSideFile {
  name: string;
  npv_rub: number;
  npv_bln_rub: number;
  run_id: string;
  run_status: string;
  sound: boolean;
  violations: ComparisonViolations;
  wallclock_seconds: number;
  opm_runs: number;
}

export interface ComparisonDeltaFile {
  npv_rub: number;
  npv_bln_rub: number;
  npv_percent: number;
  blocking_violations: number | null;
  wallclock_seconds: number;
}

export interface ComparisonConditionsFile {
  equal: boolean;
  case_path: string;
  case_hash: string;
  deck_hash: string;
  opm_image: string;
  git_commit: string | null;
}

export interface ComparisonFile {
  schema_version: number;
  run_id: string;
  conditions: ComparisonConditionsFile;
  baseline: ComparisonSideFile;
  candidate: ComparisonSideFile;
  delta: ComparisonDeltaFile;
  table: ComparisonRowFile[];
}
