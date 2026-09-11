import type { WellsFile } from '@/entities/wells/types';
import { isArtifactMeta, isNum, isRecord, isSafeArray, isStr } from '@/shared/api/guards';

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

export const isLayerRange = (data: unknown): boolean =>
  isRecord(data) && isNum(data.id) && isNum(data.k_min) && isNum(data.k_max);

export const isWellsFile = (data: unknown): data is WellsFile =>
  isRecord(data) &&
  isArtifactMeta(data.meta) &&
  isGridSize(data.grid) &&
  isSafeArray(data.layers) &&
  data.layers.every(isLayerRange) &&
  isSafeArray(data.wells) &&
  data.wells.every(isWellPoint);
