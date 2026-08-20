import type {
  GraphFile,
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

const isScenarioEntry = (data: unknown): boolean =>
  isRecord(data) && isStr(data.id) && isRecord(data.constraints);

export const isScenariosFile = (data: unknown): data is ScenariosFile =>
  isRecord(data) &&
  isSafeArray(data.scenarios) &&
  data.scenarios.every(isScenarioEntry);

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
