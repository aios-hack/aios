import type { PatternPayload } from '@/jarvis/cards/payloads/payloadTypes';
import { isNum, isRecord, isStr, numbersOf } from '@/jarvis/cards/payloads/payloadPrimitives';

export const readPattern = (payload: unknown): PatternPayload | null => {
  if (!isRecord(payload) || !isStr(payload.pattern_id) || !isStr(payload.well)) {
    return null;
  }
  const range = isRecord(payload.window) ? payload.window : {};
  return {
    pattern_id: payload.pattern_id,
    name: isStr(payload.name) ? payload.name : payload.pattern_id,
    well: payload.well,
    severity: isStr(payload.severity) ? payload.severity : '',
    window: {
      from_step: isNum(range.from_step) ? range.from_step : 0,
      to_step: isNum(range.to_step) ? range.to_step : 0
    },
    inputs: numbersOf(payload.inputs)
  };
};
