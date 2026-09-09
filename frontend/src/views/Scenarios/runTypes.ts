export type RunManifest = {
  status?: string | null;
  predicted_npv: number | null;
  verified_npv: number | null;
  sound: boolean | null;
  schedule_hash?: string | null;
  model_version?: string | null;
  npv_head_version?: string | null;
  scenario_ood_version?: string | null;
  feature_context_sha256?: string | null;
  constraints_hash?: string | null;
  deck_hash?: string | null;
  normatives_sha256?: string | null;
  opm_image?: string | null;
  git_commit?: string | null;
  seed?: string | null;
  search_strategy?: string | null;
  policy_equilibrium?: string | null;
  iterations?: number | null;
  self_consistent?: boolean | null;
  selected_candidate?: string | null;
};

export type RunSubmission = {
  canonical_schedule_hash?: string | null;
  content_hash_submission?: string | null;
  claimed_npv_rub?: number | null;
  source_run_id?: string | null;
  response_hash?: string | null;
  deck_hash?: string | null;
  economics_config_hash?: string | null;
  methodology_version_hash?: string | null;
  constraints_hash?: string | null;
  opm_image?: string | null;
  git_commit?: string | null;
  created_at?: string | null;
  schedule_present?: boolean;
};
