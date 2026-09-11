import type { HierarchyFile, HierarchyIndexFile, HierarchyStep } from '@/entities/hierarchy/types';
import { isAbsent, isArtifactMeta, isFilledArray, isNum, isNumericRecord, isRecord, isSafeArray, isStr, isStrOrNull } from '@/shared/api/guards';

const isFieldAllocation = (data: unknown): boolean =>
  isRecord(data) && isStr(data.group) && isNum(data.limit_m3_per_day);

const isHierarchyFieldLevel = (data: unknown): boolean =>
  isRecord(data) &&
  isNum(data.injection_limit_m3_per_day) &&
  (data.water_available_m3_per_day === null ||
    isNum(data.water_available_m3_per_day)) &&
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

export const isHierarchyStepFile = (data: unknown): data is HierarchyStep =>
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
  data.steps.every(isHierarchyStepFile);


export const isHierarchyIndexFile = (data: unknown): data is HierarchyIndexFile =>
  isRecord(data) &&
  isNum(data.n_control_dates) &&
  isSafeArray(data.groups) &&
  data.groups.every(isStr) &&
  isSafeArray(data.ungrouped) &&
  data.ungrouped.every(isStr) &&
  isNum(data.step_count) &&
  isStr(data.step_path);
