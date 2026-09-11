import type { GraphFile } from '@/entities/graph/types';
import { isFilledArray, isNum, isOptionalStr, isRecord, isSafeArray, isStr, isStrOrNull } from '@/shared/api/guards';

const GRAPH_ROLES: readonly unknown[] = ['INJ', 'PROD'];


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
  isOptionalStr(data.notice) &&
  isOptionalStr(data.notice_key);

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
