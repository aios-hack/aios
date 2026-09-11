import type { TimelineFile } from '@/entities/timeline/types';
import { isAbsent, isArtifactMeta, isBoolOrNull, isFilledArray, isNum, isNumOrNull, isRecord, isSafeArray, isStr, isStrArray } from '@/shared/api/guards';

const WELL_AVAILABILITY: readonly unknown[] = ['AVAILABLE', 'NOT_COMMISSIONED'];

const WELL_ROLES: readonly unknown[] = ['INJ', 'PROD', 'NONE'];

const WELL_OPERATING_STATUS: readonly unknown[] = ['OPEN', 'SHUT'];

const isFieldStats = (data: unknown): boolean =>
  isRecord(data) &&
  isNumOrNull(data.production) &&
  isNumOrNull(data.injection) &&
  isNumOrNull(data.compensation) &&
  (isAbsent(data.compensation_surface) || isNumOrNull(data.compensation_surface)) &&
  (isAbsent(data.compensation_reservoir) || isNumOrNull(data.compensation_reservoir)) &&
  (isAbsent(data.compensation_defined) || isBoolOrNull(data.compensation_defined)) &&
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
  isAbsent(value) ||
  (isRecord(value) &&
    isNum(value.min) &&
    isNum(value.max) &&
    (isAbsent(value.source) || isStr(value.source)) &&
    (isAbsent(value.enforcement) || isStr(value.enforcement)) &&
    (isAbsent(value.scope) || isStr(value.scope)) &&
    (isAbsent(value.basis) || isStr(value.basis)));

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
