import type { TraceFile } from '@/entities/trace/types';
import { isArtifactMeta, isNumericRecord, isOwnRecord, isRecord, isSafeArray, isStr, ownValues } from '@/shared/api/guards';

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
