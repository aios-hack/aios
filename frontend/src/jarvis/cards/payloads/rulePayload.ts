import type { RulePayload } from '@/jarvis/cards/payloads/payloadTypes';
import { isRecord, isStr, numOrNull, numbersOf, strOrNull } from '@/jarvis/cards/payloads/payloadPrimitives';

export const readRule = (payload: unknown): RulePayload | null => {
  if (!isRecord(payload) || !isStr(payload.rule)) {
    return null;
  }
  return {
    rule: payload.rule,
    name: isStr(payload.name) ? payload.name : payload.rule,
    statement: isStr(payload.statement) ? payload.statement : '',
    inputs: numbersOf(payload.inputs),
    decision: isStr(payload.decision) ? payload.decision : '',
    why: strOrNull(payload.why),
    delta_npv: numOrNull(payload.delta_npv) ?? numOrNull(payload.delta),
    share: numOrNull(payload.share)
  };
};
