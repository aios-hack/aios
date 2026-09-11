import type { RunRow } from '@/jarvis/cards/payloads/systemTypes';
import { boolOrNull } from '@/jarvis/cards/payloads/scalars';
import { isRecord, isStr, numOrNull, strOrNull } from '@/jarvis/cards/payloads/payloadPrimitives';

export const runRow = (value: unknown): RunRow | null => {
  if (!isRecord(value) || !isStr(value.run_id)) {
    return null;
  }
  return {
    run_id: value.run_id,
    ts: isStr(value.ts) ? value.ts : '',
    status: strOrNull(value.status),
    predicted_npv: numOrNull(value.predicted_npv),
    verified_npv: numOrNull(value.verified_npv),
    sound: boolOrNull(value.sound),
    strategy: strOrNull(value.strategy),
    seed: numOrNull(value.seed)
  };
};
