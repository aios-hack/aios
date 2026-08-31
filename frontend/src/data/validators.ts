import type {
  AblationFile,
  GraphFile,
  HierarchyFile,
  NpvFile,
  ScenariosFile,
  TimelineFile,
  TraceFile,
  WellsFile
} from '../api/types';

const MAX_ITEMS = 200000;

const isRecord = (data: unknown): data is Record<string, unknown> =>
  typeof data === 'object' && data !== null && !Array.isArray(data);

const isSafeArray = (data: unknown): data is unknown[] =>
  Array.isArray(data) && data.length <= MAX_ITEMS;

const isFilledArray = (data: unknown): data is unknown[] =>
  isSafeArray(data) && data.length > 0;

const isNum = (value: unknown): value is number =>
  typeof value === 'number' && Number.isFinite(value);

const isNumOrNull = (value: unknown): boolean => value === null || isNum(value);

const isStr = (value: unknown): value is string => typeof value === 'string';

const isStrOrNull = (value: unknown): boolean => value === null || isStr(value);

const isAbsent = (value: unknown): boolean => value === undefined || value === null;

const UNSAFE_KEYS = ['__proto__', 'constructor', 'prototype'];

const isOwnRecord = (data: unknown): data is Record<string, unknown> =>
  isRecord(data) &&
  Object.keys(data).length <= MAX_ITEMS &&
  !UNSAFE_KEYS.some((key) => Object.prototype.hasOwnProperty.call(data, key));

const ownValues = (data: Record<string, unknown>): unknown[] =>
  Object.keys(data).map((key) => data[key]);

const isNumericRecord = (data: unknown): boolean =>
  isOwnRecord(data) && ownValues(data).every(isNum);

const isBool = (value: unknown): value is boolean => typeof value === 'boolean';

const isBoolOrNull = (value: unknown): boolean => value === null || isBool(value);

const isStrArray = (data: unknown): boolean => isSafeArray(data) && data.every(isStr);

const isNumArray = (data: unknown): boolean => isSafeArray(data) && data.every(isNum);

const isOptionalStr = (value: unknown): boolean => isAbsent(value) || isStr(value);

const isArtifactMeta = (value: unknown): boolean =>
  isAbsent(value) ||
  (isRecord(value) &&
    isStr(value.kind) &&
    isStr(value.provenance) &&
    (isAbsent(value.seed) || isNum(value.seed)) &&
    isOptionalStr(value.notice_ru) &&
    isOptionalStr(value.notice_en));

const GRAPH_ROLES: readonly unknown[] = ['INJ', 'PROD'];

const WELL_AVAILABILITY: readonly unknown[] = ['AVAILABLE', 'NOT_COMMISSIONED'];

const WELL_ROLES: readonly unknown[] = ['INJ', 'PROD', 'NONE'];

const WELL_OPERATING_STATUS: readonly unknown[] = ['OPEN', 'SHUT'];

const isFieldStats = (data: unknown): boolean =>
  isRecord(data) &&
  isNumOrNull(data.production) &&
  isNumOrNull(data.injection) &&
  isNumOrNull(data.compensation) &&
  isNum(data.npv_cumulative) &&
  isNum(data.active_wells);

const isWellRow = (data: unknown): boolean =>
  isRecord(data) &&
  isStr(data.well) &&
  WELL_AVAILABILITY.includes(data.availability) &&
  WELL_ROLES.includes(data.role) &&
  WELL_OPERATING_STATUS.includes(data.operating_status) &&
  (isAbsent(data.explanation) || isStr(data.explanation)) &&
  isNum(data.setpoint) &&
  isNum(data.liquid_rate) &&
  isNum(data.injection_rate) &&
  isNum(data.bhp) &&
  isNumOrNull(data.watercut) &&
  isNumOrNull(data.fact_to_target) &&
  isNum(data.cumulative_liquid);

const isStep = (data: unknown): boolean =>
  isRecord(data) &&
  isNum(data.control_step) &&
  isStr(data.date) &&
  typeof data.terminal === 'boolean' &&
  isFieldStats(data.field) &&
  isSafeArray(data.wells) &&
  data.wells.every(isWellRow);

const isNormBand = (value: unknown): boolean =>
  isAbsent(value) || (isRecord(value) && isNum(value.min) && isNum(value.max));

const isFieldNorms = (value: unknown): boolean =>
  isAbsent(value) || (isRecord(value) && isNormBand(value.compensation));

export const isTimelineFile = (data: unknown): data is TimelineFile =>
  isRecord(data) &&
  isArtifactMeta(data.meta) &&
  isStr(data.model) &&
  isStr(data.t0) &&
  isNum(data.n_control_dates) &&
  data.n_control_dates >= 0 &&
  isNum(data.n_intervals) &&
  data.n_intervals >= 0 &&
  isStrArray(data.wells) &&
  isFieldNorms(data.field_norms) &&
  isFilledArray(data.steps) &&
  data.steps.every(isStep);

const isTraceRecord = (data: unknown): boolean =>
  isRecord(data) &&
  isStr(data.rule) &&
  isStr(data.decision) &&
  isNumericRecord(data.inputs);

const isTraceSteps = (data: unknown): boolean =>
  isOwnRecord(data) &&
  ownValues(data).every((entry) => isSafeArray(entry) && entry.every(isTraceRecord));

const META_KEY = '__meta__';

export const isTraceFile = (data: unknown): data is TraceFile =>
  isOwnRecord(data) &&
  isArtifactMeta(data[META_KEY]) &&
  Object.keys(data)
    .filter((key) => key !== META_KEY)
    .every((key) => isTraceSteps(data[key]));

const isGraphNode = (data: unknown): boolean =>
  isRecord(data) &&
  isStr(data.id) &&
  isNum(data.x) &&
  isNum(data.y) &&
  GRAPH_ROLES.includes(data.role) &&
  isStrOrNull(data.group);

const isGraphEdge = (data: unknown): boolean =>
  isRecord(data) &&
  isStr(data.injector) &&
  isStr(data.producer) &&
  isNum(data.weight);

const isGraphGroup = (data: unknown): boolean =>
  isRecord(data) &&
  isStr(data.id) &&
  isSafeArray(data.wells) &&
  data.wells.every(isStr);

const isWeightRange = (data: unknown): boolean =>
  isRecord(data) && isNum(data.min) && isNum(data.max);

const GRAPH_META_NUMBERS = [
  'lag_months',
  'amplitude',
  'stability',
  'rank',
  'condition_number'
];

const isGraphMeta = (data: unknown): boolean =>
  isRecord(data) &&
  GRAPH_META_NUMBERS.every((key) => isNum(data[key])) &&
  isOptionalStr(data.kind) &&
  isOptionalStr(data.provenance) &&
  isOptionalStr(data.notice_ru) &&
  isOptionalStr(data.notice_en);

const isGraphLayout = (data: unknown): boolean =>
  isRecord(data) && isNum(data.size) && isNum(data.seed);

export const isGraphFile = (data: unknown): data is GraphFile => {
  if (!isRecord(data)) {
    return false;
  }
  const window = data.window;
  return (
    isGraphMeta(data.meta) &&
    isGraphLayout(data.layout) &&
    isFilledArray(data.nodes) &&
    data.nodes.every(isGraphNode) &&
    isSafeArray(data.edges) &&
    data.edges.every(isGraphEdge) &&
    isSafeArray(data.groups) &&
    data.groups.every(isGraphGroup) &&
    isWeightRange(data.weight_range) &&
    isRecord(window) &&
    isStr(window.start) &&
    isStr(window.end)
  );
};

const isNpvRow = (data: unknown): boolean =>
  isRecord(data) &&
  isStr(data.well) &&
  isNum(data.pre_tax) &&
  isNum(data.with_allocated_tax);

export const isNpvFile = (data: unknown): data is NpvFile =>
  isRecord(data) &&
  isArtifactMeta(data.meta) &&
  isNum(data.npv_methodology) &&
  isFilledArray(data.wells) &&
  data.wells.every(isNpvRow) &&
  isRecord(data.total) &&
  isNum(data.total.pre_tax) &&
  isNum(data.total.with_allocated_tax);

const REGRET_PARTS = ['optimization', 'holdout'];

const isOptionalNum = (value: unknown): boolean => isAbsent(value) || isNum(value);

const isWorstRegret = (value: unknown): boolean =>
  isAbsent(value) ||
  (isRecord(value) &&
    isStr(value.scenario_id) &&
    isNum(value.value_rub) &&
    isStr(value.part) &&
    REGRET_PARTS.includes(value.part));

const isFinalNpv = (value: unknown): boolean =>
  isAbsent(value) ||
  (isRecord(value) && isNum(value.npv_rub) && isStr(value.run_id));

const CONSTRAINT_COUNTS = [
  'injection_limits',
  'liquid_limits',
  'production_floors',
  'watercut_limits',
  'well_outages',
  'infrastructure'
];

const isConstraintsSummary = (data: unknown): boolean =>
  isRecord(data) &&
  CONSTRAINT_COUNTS.every((key) => isNum(data[key])) &&
  isNumArray(data.years) &&
  isStrArray(data.outage_wells) &&
  isBool(data.empty);

const isScenarioEntry = (data: unknown): boolean =>
  isRecord(data) &&
  isStr(data.id) &&
  isStr(data.config_hash) &&
  isBool(data.converged) &&
  isBool(data.self_consistent) &&
  isBool(data.is_submitted) &&
  isNumOrNull(data.npv_methodology) &&
  (isAbsent(data.run_validation_clean) || isBoolOrNull(data.run_validation_clean)) &&
  isConstraintsSummary(data.constraints) &&
  isOptionalNum(data.ood_score) &&
  isOptionalNum(data.ood_threshold) &&
  isOptionalNum(data.predicted_npv_rub) &&
  isOptionalNum(data.calibrated_npv_rub) &&
  isWorstRegret(data.worst_regret) &&
  isFinalNpv(data.final_npv);

export const isScenariosFile = (data: unknown): data is ScenariosFile =>
  isRecord(data) &&
  isArtifactMeta(data.meta) &&
  isStrOrNull(data.submitted) &&
  isSafeArray(data.scenarios) &&
  data.scenarios.every(isScenarioEntry);

const isAblationRule = (data: unknown): boolean =>
  isRecord(data) &&
  isStr(data.rule) &&
  typeof data.enabled === 'boolean' &&
  isNumOrNull(data.delta_npv) &&
  isNumOrNull(data.share) &&
  (isAbsent(data.disabled_reason) || isStr(data.disabled_reason));

export const isAblationFile = (data: unknown): data is AblationFile =>
  isRecord(data) &&
  isArtifactMeta(data.meta) &&
  isNum(data.npv_total) &&
  isFilledArray(data.rules) &&
  data.rules.every(isAblationRule);

const isExtent = (value: unknown): boolean => isNum(value) && value > 0;

const isGridSize = (data: unknown): boolean =>
  isRecord(data) && isExtent(data.ni) && isExtent(data.nj) && isExtent(data.nk);

const isCompletion = (data: unknown): boolean =>
  Array.isArray(data) && data.length === 2 && data.every(isNum);

const isWellPoint = (data: unknown): boolean =>
  isRecord(data) &&
  isStr(data.id) &&
  isNum(data.i) &&
  isNum(data.j) &&
  isSafeArray(data.layers) &&
  data.layers.every(isNum) &&
  isSafeArray(data.completions) &&
  data.completions.every(isCompletion);

const isLayerRange = (data: unknown): boolean =>
  isRecord(data) && isNum(data.id) && isNum(data.k_min) && isNum(data.k_max);

export const isWellsFile = (data: unknown): data is WellsFile =>
  isRecord(data) &&
  isArtifactMeta(data.meta) &&
  isGridSize(data.grid) &&
  isSafeArray(data.layers) &&
  data.layers.every(isLayerRange) &&
  isSafeArray(data.wells) &&
  data.wells.every(isWellPoint);

const isFieldAllocation = (data: unknown): boolean =>
  isRecord(data) && isStr(data.group) && isNum(data.limit_m3_per_day);

const isHierarchyFieldLevel = (data: unknown): boolean =>
  isRecord(data) &&
  isNum(data.injection_limit_m3_per_day) &&
  isNum(data.water_available_m3_per_day) &&
  isSafeArray(data.allocations) &&
  data.allocations.every(isFieldAllocation);

const isGroupAllocation = (data: unknown): boolean =>
  isRecord(data) && isStr(data.well) && isNum(data.value_m3_per_day);

const isHierarchyGroupLevel = (data: unknown): boolean =>
  isRecord(data) &&
  isStr(data.group) &&
  isNum(data.received_m3_per_day) &&
  isSafeArray(data.allocations) &&
  data.allocations.every(isGroupAllocation);

const isHierarchyWell = (data: unknown): boolean =>
  isRecord(data) &&
  isStr(data.well) &&
  isStrOrNull(data.group) &&
  isStr(data.decision) &&
  isStr(data.rule) &&
  isNumericRecord(data.inputs) &&
  isStrOrNull(data.constraint);

const isHierarchyStep = (data: unknown): boolean =>
  isRecord(data) &&
  isNum(data.control_step) &&
  isHierarchyFieldLevel(data.field) &&
  isSafeArray(data.groups) &&
  data.groups.every(isHierarchyGroupLevel) &&
  (isAbsent(data.ungrouped) ||
    (isSafeArray(data.ungrouped) && data.ungrouped.every(isGroupAllocation))) &&
  isSafeArray(data.wells) &&
  data.wells.every(isHierarchyWell);

export const isHierarchyFile = (data: unknown): data is HierarchyFile =>
  isRecord(data) &&
  isArtifactMeta(data.meta) &&
  isNum(data.n_control_dates) &&
  isSafeArray(data.groups) &&
  data.groups.every(isStr) &&
  isSafeArray(data.ungrouped) &&
  data.ungrouped.every(isStr) &&
  isFilledArray(data.steps) &&
  data.steps.every(isHierarchyStep);
