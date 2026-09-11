import type { SeriesPayload } from '@/jarvis/cards/payloads/payloadTypes';
import { isNum, isRecord, isStr, list, numOrNull } from '@/jarvis/cards/payloads/payloadPrimitives';

export const readSeries = (payload: unknown): SeriesPayload | null => {
  if (!isRecord(payload)) {
    return null;
  }
  const rows = list(payload.rows)
    .filter((row): row is Record<string, unknown> => isRecord(row) && isNum(row.step))
    .map((row) => ({
      step: row.step as number,
      date: isStr(row.date) ? row.date : '',
      value: numOrNull(row.value)
    }));
  if (rows.length === 0) {
    return null;
  }
  const range = list(payload.window);
  return {
    metric: isStr(payload.metric) ? payload.metric : '',
    unit: isStr(payload.unit) ? payload.unit : '',
    rows,
    window: range.length === 2 && isNum(range[0]) && isNum(range[1]) ? [range[0], range[1]] : null
  };
};
