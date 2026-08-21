import type {
  AblationFile,
  DemoScriptFile,
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
  isStr(data.availability) &&
  isStr(data.role) &&
  isStr(data.operating_status) &&
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
  isFieldStats(data.field) &&
  isSafeArray(data.wells) &&
  data.wells.every(isWellRow);

export const isTimelineFile = (data: unknown): data is TimelineFile =>
  isRecord(data) && isFilledArray(data.steps) && data.steps.every(isStep);

export const isTraceFile = (data: unknown): data is TraceFile => isRecord(data);

const isGraphNode = (data: unknown): boolean =>
  isRecord(data) && isStr(data.id) && isNum(data.x) && isNum(data.y);

const isGraphEdge = (data: unknown): boolean =>
  isRecord(data) &&
  isStr(data.injector) &&
  isStr(data.producer) &&
  isNum(data.weight);

export const isGraphFile = (data: unknown): data is GraphFile => {
  if (!isRecord(data)) {
    return false;
  }
  const window = data.window;
  return (
    isFilledArray(data.nodes) &&
    data.nodes.every(isGraphNode) &&
    isSafeArray(data.edges) &&
    data.edges.every(isGraphEdge) &&
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
  isFilledArray(data.wells) &&
  data.wells.every(isNpvRow) &&
  isRecord(data.total) &&
  isNum(data.total.pre_tax) &&
  isNum(data.total.with_allocated_tax);

const REGRET_PARTS = ['optimization', 'holdout'];

const isAbsent = (value: unknown): boolean => value === undefined || value === null;

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

const isScenarioEntry = (data: unknown): boolean =>
  isRecord(data) &&
  isStr(data.id) &&
  isRecord(data.constraints) &&
  isOptionalNum(data.ood_score) &&
  isOptionalNum(data.ood_threshold) &&
  isWorstRegret(data.worst_regret) &&
  isFinalNpv(data.final_npv);

export const isScenariosFile = (data: unknown): data is ScenariosFile =>
  isRecord(data) &&
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
  isNum(data.npv_total) &&
  isFilledArray(data.rules) &&
  data.rules.every(isAblationRule);

const isExtent = (value: unknown): boolean => isNum(value) && value > 0;

const isGridSize = (data: unknown): boolean =>
  isRecord(data) && isExtent(data.ni) && isExtent(data.nj) && isExtent(data.nk);

const isWellPoint = (data: unknown): boolean =>
  isRecord(data) &&
  isStr(data.id) &&
  isNum(data.i) &&
  isNum(data.j) &&
  isSafeArray(data.layers) &&
  isSafeArray(data.completions);

export const isWellsFile = (data: unknown): data is WellsFile =>
  isRecord(data) &&
  isGridSize(data.grid) &&
  isSafeArray(data.layers) &&
  isSafeArray(data.wells) &&
  data.wells.every(isWellPoint);

const isStrOrNull = (value: unknown): boolean => value === null || isStr(value);

const isNumericRecord = (data: unknown): boolean =>
  isRecord(data) && Object.values(data).every(isNum);

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
  isNum(data.n_control_dates) &&
  isSafeArray(data.groups) &&
  data.groups.every(isStr) &&
  isSafeArray(data.ungrouped) &&
  data.ungrouped.every(isStr) &&
  isFilledArray(data.steps) &&
  data.steps.every(isHierarchyStep);

const isOptionalStr = (value: unknown): boolean => isAbsent(value) || isStr(value);

const isDemoEvent = (data: unknown): boolean =>
  isRecord(data) &&
  isStr(data.type) &&
  isOptionalStr(data.well) &&
  isOptionalStr(data.rule);

const isDemoFrame = (data: unknown): boolean =>
  isRecord(data) &&
  isNum(data.step) &&
  isStr(data.scene) &&
  (data.well === null || isStr(data.well)) &&
  (data.event === null || isDemoEvent(data.event)) &&
  isNum(data.hold_ms) &&
  data.hold_ms > 0 &&
  isOptionalNum(data.t);

export const isDemoScriptFile = (data: unknown): data is DemoScriptFile =>
  isRecord(data) &&
  isFilledArray(data.frames) &&
  data.frames.every(isDemoFrame) &&
  isOptionalNum(data.total_ms);
