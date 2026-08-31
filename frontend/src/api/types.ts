export interface ArtifactMeta {
  kind: string;
  provenance: string;
  seed?: number;
  notice_ru?: string;
  notice_en?: string;
}

export interface GridSize {
  ni: number;
  nj: number;
  nk: number;
}

export interface LayerRange {
  id: number;
  k_min: number;
  k_max: number;
}

export interface WellPoint {
  id: string;
  i: number;
  j: number;
  completions: [number, number][];
  layers: number[];
}

export interface WellsFile {
  meta?: ArtifactMeta;
  grid: GridSize;
  layers: LayerRange[];
  wells: WellPoint[];
}

export type WellAvailability = 'AVAILABLE' | 'NOT_COMMISSIONED';
export type WellRole = 'INJ' | 'PROD' | 'NONE';
export type WellOperatingStatus = 'OPEN' | 'SHUT';

export interface TimelineWellRow {
  well: string;
  availability: WellAvailability;
  role: WellRole;
  operating_status: WellOperatingStatus;
  setpoint: number;
  liquid_rate: number;
  injection_rate: number;
  bhp: number;
  watercut: number | null;
  fact_to_target: number | null;
  cumulative_liquid: number;
  explanation?: string | null;
}

export interface TraceRecord {
  rule: string;
  inputs: Record<string, number>;
  decision: string;
}

export type TraceFile = Record<string, Record<string, TraceRecord[]>>;

export interface TimelineFieldStats {
  production: number | null;
  injection: number | null;
  compensation: number | null;
  npv_cumulative: number;
  active_wells: number;
}

export interface TimelineStep {
  control_step: number;
  date: string;
  terminal: boolean;
  field: TimelineFieldStats;
  wells: TimelineWellRow[];
}

export interface FieldNormBand {
  min: number;
  max: number;
}

export interface TimelineFieldNorms {
  compensation?: FieldNormBand;
}

export interface TimelineFile {
  meta?: ArtifactMeta;
  model: string;
  t0: string;
  n_control_dates: number;
  n_intervals: number;
  wells: string[];
  steps: TimelineStep[];
  field_norms?: TimelineFieldNorms;
}

export interface NpvWellRow {
  well: string;
  pre_tax: number;
  with_allocated_tax: number;
}

export interface NpvTotals {
  pre_tax: number;
  with_allocated_tax: number;
}

export interface NpvFile {
  meta?: ArtifactMeta;
  wells: NpvWellRow[];
  total: NpvTotals;
  npv_methodology: number;
}

export interface AblationRule {
  rule: string;
  enabled: boolean;
  delta_npv: number | null;
  share: number | null;
  disabled_reason?: string;
}

export interface AblationFile {
  meta?: ArtifactMeta;
  npv_total: number;
  rules: AblationRule[];
}

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
}

export interface ScenariosFile {
  meta?: ArtifactMeta;
  scenarios: ScenarioEntry[];
  submitted: string | null;
}

export interface GraphNode {
  id: string;
  role: 'INJ' | 'PROD';
  group: string | null;
  x: number;
  y: number;
}

export interface GraphEdge {
  injector: string;
  producer: string;
  weight: number;
}

export interface GraphGroup {
  id: string;
  wells: string[];
}

export interface GraphWindow {
  start: string;
  end: string;
}

export interface GraphMeta {
  lag_months: number;
  amplitude: number;
  stability: number;
  rank: number;
  condition_number: number;
}

export interface GraphFile {
  window: GraphWindow;
  nodes: GraphNode[];
  edges: GraphEdge[];
  groups: GraphGroup[];
  weight_range: { min: number; max: number };
  meta: GraphMeta & Partial<ArtifactMeta>;
  layout: { size: number; seed: number };
}

export interface HierarchyFieldAllocation {
  group: string;
  limit_m3_per_day: number;
}

export interface HierarchyFieldLevel {
  injection_limit_m3_per_day: number;
  water_available_m3_per_day: number;
  allocations: HierarchyFieldAllocation[];
}

export interface HierarchyGroupAllocation {
  well: string;
  value_m3_per_day: number;
}

export interface HierarchyGroupLevel {
  group: string;
  received_m3_per_day: number;
  allocations: HierarchyGroupAllocation[];
}

export interface HierarchyWellDecision {
  well: string;
  group: string | null;
  decision: string;
  rule: string;
  inputs: Record<string, number>;
  constraint: string | null;
}

export interface HierarchyStep {
  control_step: number;
  field: HierarchyFieldLevel;
  groups: HierarchyGroupLevel[];
  ungrouped?: HierarchyGroupAllocation[];
  wells: HierarchyWellDecision[];
}

export interface HierarchyFile {
  meta?: ArtifactMeta;
  n_control_dates: number;
  groups: string[];
  ungrouped: string[];
  steps: HierarchyStep[];
}
