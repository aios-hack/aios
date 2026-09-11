import type { WellListPayload } from '@/jarvis/cards/payloads/payloadTypes';
import { isNum, isRecord, isStr, list, numOrNull } from '@/jarvis/cards/payloads/payloadPrimitives';

export const readWellList = (payload: unknown): WellListPayload | null => {
  if (!isRecord(payload)) {
    return null;
  }
  const rows = list(payload.rows)
    .filter((row): row is Record<string, unknown> => isRecord(row) && isStr(row.well))
    .filter((row) => isNum(row.value))
    .map((row) => ({
      well: row.well as string,
      value: row.value as number,
      share: numOrNull(row.share)
    }));
  if (rows.length === 0) {
    return null;
  }
  return {
    by: isStr(payload.by) ? payload.by : '',
    unit: isStr(payload.unit) ? payload.unit : '',
    order: isStr(payload.order) ? payload.order : 'desc',
    rows
  };
};
