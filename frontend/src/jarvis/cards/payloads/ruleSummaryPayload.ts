import type { RulePayload, RuleSummaryPayload } from '@/jarvis/cards/payloads/payloadTypes';
import { readRule } from '@/jarvis/cards/payloads/rulePayload';
import { isRecord, numOrNull } from '@/jarvis/cards/payloads/payloadPrimitives';

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
