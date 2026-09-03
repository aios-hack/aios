export interface SparkPoint {
  step: number;
  value: number | null;
}

export interface MetricPayload {
  id: string;
  label: string;
  value: number;
  unit: string;
  delta: number | null;
  spark: SparkPoint[];
}

export interface WellPayload {
  well: string;
  role: string;
  availability: string;
  operating_status: string;
  liquid_rate: number;
  injection_rate: number;
  watercut: number | null;
  bhp: number;
  setpoint: number;
  npv: number | null;
  spark: SparkPoint[];
}

export interface WellListRow {
  well: string;
  value: number;
  share: number | null;
}

export interface WellListPayload {
  by: string;
  unit: string;
  order: string;
  rows: WellListRow[];
}

export interface SeriesRow {
  step: number;
  date: string;
  value: number | null;
}

export interface SeriesPayload {
  metric: string;
  unit: string;
  rows: SeriesRow[];
  window: [number, number] | null;
}

export interface RulePayload {
  rule: string;
  name: string;
  statement: string;
  inputs: Record<string, number>;
  decision: string;
  why: string | null;
  delta_npv: number | null;
  share: number | null;
}

export interface RuleSummaryPayload {
  npv_total: number | null;
  rules: RulePayload[];
}

export interface CompareSide {
  id: string;
  npv: number | null;
  status: string;
  constraints: number;
}

export interface ComparePayload {
  a: CompareSide;
  b: CompareSide;
  delta_npv: number;
  top_diff_wells: { well: string; delta: number }[];
}

export interface FieldEventRow {
  step: number;
  date: string;
  well: string;
  type: string;
}

export interface EventStripPayload {
  from_step: number;
  to_step: number;
  events: FieldEventRow[];
}

export interface FieldMapEdge {
  injector: string;
  producer: string;
  weight: number;
}

export interface FieldMapPayload {
  focus: string[];
  highlight: string[];
  edges: FieldMapEdge[];
  layer: string | null;
}

export interface PatternPayload {
  pattern_id: string;
  name: string;
  well: string;
  severity: string;
  window: { from_step: number; to_step: number };
  inputs: Record<string, number>;
}

export interface ErrorPayload {
  code: string;
  tool: string | null;
  message: string;
}

export interface WhereInPlatform {
  workspace: string;
  view: string;
  what: string;
  spotlight: string | null;
}

export interface GlossaryPayload {
  id: string;
  term: string;
  definition: string;
  formula: string | null;
  unit: string | null;
  source: string | null;
  where_in_platform: WhereInPlatform[];
  related: string[];
}

export interface GuideControl {
  label: string;
  spotlight: string | null;
  hotkey: string | null;
}

export interface GuidePayload {
  workspace: string;
  view: string;
  title: string;
  what: string;
  how_to_read: string;
  controls: GuideControl[];
  questions: string[];
}
