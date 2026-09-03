import type { RulePayload, RuleSummaryPayload } from './payloadTypes';
import { isRecord, isStr, numOrNull, numbersOf, strOrNull } from './payloadPrimitives';

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

export const readRuleSummary = (payload: unknown): RuleSummaryPayload | null => {
  if (!isRecord(payload) || !Array.isArray(payload.rules)) {
    return null;
  }
  const rules = payload.rules
    .map((entry) => readRule(entry))
    .filter((entry): entry is RulePayload => entry !== null);
  if (rules.length === 0) {
    return null;
  }
  return { npv_total: numOrNull(payload.npv_total), rules };
};
