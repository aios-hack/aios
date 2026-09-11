import type { ComparisonFile, RunsResponse } from '@/entities/runs/types';
import { isAbsent, isBool, isBoolOrNull, isNum, isNumOrNull, isRecord, isSafeArray, isStr } from '@/shared/api/guards';

const isRunManifest = (data: unknown): boolean =>
  isAbsent(data) ||
  (isRecord(data) &&
    isStr(data.run_id) &&
    isStr(data.status) &&
    (isAbsent(data.predicted_npv) || isNum(data.predicted_npv)) &&
    (isAbsent(data.verified_npv) || isNum(data.verified_npv)) &&
    (isAbsent(data.sound) || isBool(data.sound)));

const isRunRow = (data: unknown): boolean =>
  isRecord(data) && isStr(data.run_id) && isStr(data.status) && isRunManifest(data.manifest);

export const isRunsResponse = (data: unknown): data is RunsResponse =>
  isRecord(data) && isSafeArray(data.runs) && data.runs.every(isRunRow);

const isComparisonViolations = (data: unknown): boolean =>
  isRecord(data) &&
  isNumOrNull(data.static ?? null) &&
  isNumOrNull(data.dynamic ?? null) &&
  isNumOrNull(data.blocking ?? null);

const isComparisonSide = (data: unknown): boolean =>
  isRecord(data) &&
  isStr(data.name) &&
  isNum(data.npv_rub) &&
  isStr(data.run_status) &&
  isBoolOrNull(data.sound ?? null) &&
  isComparisonViolations(data.violations) &&
  isNum(data.wallclock_seconds) &&
  isNum(data.opm_runs);

const isComparisonRow = (data: unknown): boolean =>
  isRecord(data) &&
  isStr(data.metric) &&
  isStr(data.baseline) &&
  isStr(data.candidate) &&
  isStr(data.delta);

export const isComparisonFile = (data: unknown): data is ComparisonFile =>
  isRecord(data) &&
  isStr(data.run_id) &&
  isRecord(data.conditions) &&
  isComparisonSide(data.baseline) &&
  isComparisonSide(data.candidate) &&
  isRecord(data.delta) &&
  isNum((data.delta as Record<string, unknown>).npv_rub) &&
  isSafeArray(data.table) &&
  data.table.every(isComparisonRow);
