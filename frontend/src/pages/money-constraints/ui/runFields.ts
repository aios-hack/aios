export const HASH_FIELDS = new Set([
  'feature_context_sha256',
  'constraints_hash',
  'deck_hash',
  'normatives_sha256',
  'git_commit',
  'canonical_schedule_hash',
  'content_hash_submission',
  'response_hash',
  'economics_config_hash',
  'methodology_version_hash',
  'schedule_hash'
]);

const FALLBACK_STRATEGIES = new Set([
  'baseline-neighborhood',
  'fallback',
  'baseline_neighborhood'
]);

const STRATEGY_KEYS: Readonly<Record<string, string>> = {
  'baseline-neighborhood': 'baseline-neighborhood',
  baseline_neighborhood: 'baseline-neighborhood',
  fallback: 'fallback',
  policy: 'policy',
  'agent-policy': 'policy'
};

const CANDIDATE_KEYS: Readonly<Record<string, string>> = {
  baseline: 'baseline',
  'local-change': 'local-change'
};

export const isFallbackStrategy = (strategy: string | null | undefined): boolean =>
  strategy !== null && strategy !== undefined && FALLBACK_STRATEGIES.has(strategy);

export const isEquilibriumUnclaimed = (equilibrium: string | null | undefined): boolean =>
  equilibrium === 'not-claimed' || equilibrium === 'not_claimed';

export const strategyKeyOf = (value: string): string | null =>
  STRATEGY_KEYS[value] ?? null;

export const candidateKeyOf = (value: string): string | null =>
  CANDIDATE_KEYS[value] ?? null;

export const HOW_FIELDS = [
  'search_strategy',
  'selected_candidate',
  'policy_equilibrium',
  'iterations',
  'self_consistent',
  'seed'
];

export const VERSION_FIELDS = [
  'model_version',
  'npv_head_version',
  'scenario_ood_version',
  'opm_image',
  'git_commit'
];

export const HASH_ROWS = [
  'schedule_hash',
  'constraints_hash',
  'deck_hash',
  'feature_context_sha256',
  'normatives_sha256'
];

export const BUNDLE_FIELDS = [
  'canonical_schedule_hash',
  'content_hash_submission',
  'response_hash',
  'deck_hash',
  'constraints_hash',
  'economics_config_hash',
  'methodology_version_hash',
  'opm_image',
  'git_commit',
  'source_run_id',
  'created_at'
];
