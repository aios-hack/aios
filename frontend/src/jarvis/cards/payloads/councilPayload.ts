import type { CouncilLevel, CouncilPayload } from '@/jarvis/cards/payloads/systemTypes';
import { isNum, isRecord, isStr, list, strOrNull } from '@/jarvis/cards/payloads/payloadPrimitives';

const councilLevel = (value: unknown): CouncilLevel | null => {
  if (!isRecord(value) || !isStr(value.agent)) {
    return null;
  }
  return {
    rank: isNum(value.rank) ? value.rank : 0,
    agent: value.agent,
    level: strOrNull(value.level),
    verdict: strOrNull(value.verdict) ?? '',
    bounds: list(value.bounds).filter(isNum),
    decisions: list(value.decisions).length
  };
};

export const readCouncil = (payload: unknown): CouncilPayload | null => {
  if (!isRecord(payload) || !isNum(payload.step)) {
    return null;
  }
  const levels = list(payload.levels)
    .map(councilLevel)
    .filter((level): level is CouncilLevel => level !== null)
    .sort((a, b) => a.rank - b.rank);
  if (levels.length === 0) {
    return null;
  }
  const outcome = isRecord(payload.outcome) ? payload.outcome : {};
  return {
    step: payload.step,
    date: strOrNull(payload.date),
    group: strOrNull(payload.group),
    agents_fired: list(payload.agents_fired).filter(isStr),
    levels,
    outcome: {
      well: strOrNull(outcome.well),
      action: strOrNull(outcome.action) ?? strOrNull(outcome.decision),
      rule: strOrNull(outcome.rule)
    }
  };
};
