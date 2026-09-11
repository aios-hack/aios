import type { NpvFile } from '@/entities/npv/types';
import { isArtifactMeta, isFilledArray, isNum, isRecord, isStr } from '@/shared/api/guards';

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
