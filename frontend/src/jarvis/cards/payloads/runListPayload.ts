import type { RunListPayload, RunRow } from '@/jarvis/cards/payloads/systemTypes';
import { runRow } from '@/jarvis/cards/payloads/runRow';
import { isNum, isRecord, list } from '@/jarvis/cards/payloads/payloadPrimitives';

export const readRunList = (payload: unknown): RunListPayload | null => {
  if (!isRecord(payload)) {
    return null;
  }
  const rows = list(payload.rows)
    .map(runRow)
    .filter((row): row is RunRow => row !== null);
  if (rows.length === 0) {
    return null;
  }
  return { rows, total: isNum(payload.total) ? payload.total : rows.length };
};
