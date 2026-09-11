export const MAX_ITEMS = 200000;

export const isRecord = (data: unknown): data is Record<string, unknown> =>
  typeof data === 'object' && data !== null && !Array.isArray(data);

export const isSafeArray = (data: unknown): data is unknown[] =>
  Array.isArray(data) && data.length <= MAX_ITEMS;

export const isFilledArray = (data: unknown): data is unknown[] =>
  isSafeArray(data) && data.length > 0;

export const isNum = (value: unknown): value is number =>
  typeof value === 'number' && Number.isFinite(value);

export const isNumOrNull = (value: unknown): boolean => value === null || isNum(value);

export const isStr = (value: unknown): value is string => typeof value === 'string';

export const isStrOrNull = (value: unknown): boolean => value === null || isStr(value);

export const isAbsent = (value: unknown): boolean => value === undefined || value === null;

export const UNSAFE_KEYS = ['__proto__', 'constructor', 'prototype'];

export const isOwnRecord = (data: unknown): data is Record<string, unknown> =>
  isRecord(data) &&
  Object.keys(data).length <= MAX_ITEMS &&
  !UNSAFE_KEYS.some((key) => Object.prototype.hasOwnProperty.call(data, key));

export const ownValues = (data: Record<string, unknown>): unknown[] =>
  Object.keys(data).map((key) => data[key]);

export const isNumericRecord = (data: unknown): boolean =>
  isOwnRecord(data) && ownValues(data).every(isNum);

export const isBool = (value: unknown): value is boolean => typeof value === 'boolean';

export const isBoolOrNull = (value: unknown): boolean => value === null || isBool(value);

export const isStrArray = (data: unknown): boolean => isSafeArray(data) && data.every(isStr);

export const isNumArray = (data: unknown): boolean => isSafeArray(data) && data.every(isNum);

export const isOptionalStr = (value: unknown): boolean => isAbsent(value) || isStr(value);

export const isArtifactMeta = (value: unknown): boolean =>
  isAbsent(value) ||
  (isRecord(value) &&
    isStr(value.kind) &&
    isStr(value.provenance) &&
    (isAbsent(value.synthetic) || isBool(value.synthetic)) &&
    (isAbsent(value.seed) || isNum(value.seed)) &&
    isOptionalStr(value.notice) &&
    isOptionalStr(value.notice_key));

