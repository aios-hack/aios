import type { MetricPayload } from '@/jarvis/cards/payloads/payloadTypes';
import { isNum, isRecord, isStr, numOrNull, sparkOf } from '@/jarvis/cards/payloads/payloadPrimitives';

export const readMetric = (payload: unknown): MetricPayload | null => {
  if (!isRecord(payload) || !isStr(payload.label) || !isNum(payload.value)) {
    return null;
  }
  return {
    id: isStr(payload.id) ? payload.id : payload.label,
    label: payload.label,
    value: payload.value,
    unit: isStr(payload.unit) ? payload.unit : '',
    delta: numOrNull(payload.delta),
    spark: sparkOf(payload.spark)
  };
};

export const readMetrics = (payload: unknown): MetricPayload[] => {
  if (isRecord(payload) && Array.isArray(payload.metrics)) {
    return payload.metrics
      .map((entry) => readMetric(entry))
      .filter((entry): entry is MetricPayload => entry !== null);
  }
  if (Array.isArray(payload)) {
    return payload
      .map((entry) => readMetric(entry))
      .filter((entry): entry is MetricPayload => entry !== null);
  }
  const single = readMetric(payload);
  return single === null ? [] : [single];
};
