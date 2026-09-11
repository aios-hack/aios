import type {
  CompareConstraints,
  ComparePayload,
  CompareSide,
  CompareStatus
} from '@/jarvis/cards/payloads/payloadTypes';
import { isNum, isRecord, isStr, list, numOrNull, strOrNull } from '@/jarvis/cards/payloads/payloadPrimitives';

const NUMERIC_SKIP = new Set(['empty', 'recorded']);

const compareStatus = (value: unknown): CompareStatus => {
  if (!isRecord(value)) {
    return {
      status: isStr(value) ? value : null,
      sound: null,
      converged: null,
      self_consistent: null,
      ood_score: null,
      ood_threshold: null,
      has_submission: null,
      opm_status: null
    };
  }
  const flag = (key: string): boolean | null =>
    typeof value[key] === 'boolean' ? (value[key] as boolean) : null;
  return {
    status: strOrNull(value.status),
    sound: flag('sound'),
    converged: flag('converged'),
    self_consistent: flag('self_consistent'),
    ood_score: numOrNull(value.ood_score),
    ood_threshold: numOrNull(value.ood_threshold),
    has_submission: flag('has_submission'),
    opm_status: strOrNull(value.opm_status)
  };
};

const compareConstraints = (value: unknown): CompareConstraints => {
  if (isNum(value)) {
    return { total: value, empty: value === 0, groups: [] };
  }
  if (!isRecord(value)) {
    return { total: null, empty: null, groups: [] };
  }
  const groups: { key: string; count: number }[] = [];
  let total = 0;
  for (const key of Object.keys(value)) {
    if (NUMERIC_SKIP.has(key)) {
      continue;
    }
    const entry = value[key];
    if (!isNum(entry)) {
      continue;
    }
    groups.push({ key, count: entry });
    total += entry;
  }
  const dynamic = numOrNull(value.dynamic_violations);
  return {
    total: groups.length === 0 ? dynamic : total,
    empty: typeof value.empty === 'boolean' ? value.empty : null,
    groups
  };
};

const compareSide = (value: unknown): CompareSide | null => {
  if (!isRecord(value) || !isStr(value.id)) {
    return null;
  }
  return {
    id: value.id,
    npv: numOrNull(value.npv),
    status: compareStatus(value.status),
    constraints: compareConstraints(value.constraints)
  };
};

export const readCompare = (payload: unknown): ComparePayload | null => {
  if (!isRecord(payload)) {
    return null;
  }
  const a = compareSide(payload.a);
  const b = compareSide(payload.b);
  if (a === null || b === null) {
    return null;
  }
  return {
    a,
    b,
    delta_npv: numOrNull(payload.delta_npv),
    top_diff_wells: list(payload.top_diff_wells)
      .filter((row): row is Record<string, unknown> => isRecord(row) && isStr(row.well))
      .filter((row) => isNum(row.delta))
      .map((row) => ({ well: row.well as string, delta: row.delta as number })),
    comparison_reason: strOrNull(payload.comparison_reason)
  };
};
