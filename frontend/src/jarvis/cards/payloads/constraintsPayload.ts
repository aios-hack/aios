import type { ConstraintRow, ConstraintsPayload } from '@/jarvis/cards/payloads/systemTypes';
import { scalar } from '@/jarvis/cards/payloads/scalars';
import { isRecord, isStr, list, strOrNull } from '@/jarvis/cards/payloads/payloadPrimitives';

const constraintRow = (value: unknown): ConstraintRow | null => {
  if (!isRecord(value) || !isStr(value.key)) {
    return null;
  }
  return {
    key: value.key,
    group: strOrNull(value.group),
    value: scalar(value.value),
    unit: strOrNull(value.unit),
    source: strOrNull(value.source),
    empty: value.empty === true
  };
};

export const readConstraints = (payload: unknown): ConstraintsPayload | null => {
  if (!isRecord(payload)) {
    return null;
  }
  const items = list(payload.items)
    .map(constraintRow)
    .filter((row): row is ConstraintRow => row !== null);
  if (items.length === 0) {
    return null;
  }
  return { case: isStr(payload.case) ? payload.case : '', items };
};
