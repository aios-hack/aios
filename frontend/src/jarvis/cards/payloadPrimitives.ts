import type { SparkPoint } from './payloadTypes';

export const isRecord = (value: unknown): value is Record<string, unknown> =>
  typeof value === 'object' && value !== null && !Array.isArray(value);

export const isNum = (value: unknown): value is number =>
  typeof value === 'number' && Number.isFinite(value);

export const isStr = (value: unknown): value is string => typeof value === 'string';

export const numOrNull = (value: unknown): number | null => (isNum(value) ? value : null);
export const strOrNull = (value: unknown): string | null => (isStr(value) ? value : null);

export const list = (value: unknown): unknown[] => (Array.isArray(value) ? value : []);

export const numbersOf = (value: unknown): Record<string, number> => {
  if (!isRecord(value)) {
    return {};
  }
  const out: Record<string, number> = {};
  for (const key of Object.keys(value)) {
    const entry = value[key];
    if (isNum(entry)) {
      out[key] = entry;
    }
  }
  return out;
};

export const textOf = (value: unknown, lang = 'ru'): string | null => {
  if (isStr(value)) {
    return value;
  }
  if (!isRecord(value)) {
    return null;
  }
  const picked = value[lang];
  if (isStr(picked)) {
    return picked;
  }
  return isStr(value.ru) ? value.ru : isStr(value.en) ? value.en : null;
};

export const sparkOf = (value: unknown): SparkPoint[] =>
  list(value)
    .filter((point): point is Record<string, unknown> => isRecord(point) && isNum(point.step))
    .map((point) => ({ step: point.step as number, value: numOrNull(point.value) }));
