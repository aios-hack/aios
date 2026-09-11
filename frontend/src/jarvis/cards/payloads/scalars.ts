import { isNum, isStr } from '@/jarvis/cards/payloads/payloadPrimitives';

export const boolOrNull = (value: unknown): boolean | null =>
  typeof value === 'boolean' ? value : null;

export const scalar = (value: unknown): string | number | boolean | null => {
  if (isNum(value) || isStr(value) || typeof value === 'boolean') {
    return value;
  }
  return null;
};
