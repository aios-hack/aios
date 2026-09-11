import type { RunPayload } from '@/jarvis/cards/payloads/systemTypes';
import { readPhysics } from '@/jarvis/cards/payloads/physicsPayload';
import { runRow } from '@/jarvis/cards/payloads/runRow';
import { isRecord, list, numOrNull, strOrNull } from '@/jarvis/cards/payloads/payloadPrimitives';

export const readRun = (payload: unknown): RunPayload | null => {
  const row = runRow(payload);
  if (row === null || !isRecord(payload)) {
    return null;
  }
  return {
    ...row,
    schedule_hash: strOrNull(payload.schedule_hash),
    claimed_npv: numOrNull(payload.claimed_npv_rub),
    has_submission: payload.has_submission === true,
    violations: list(payload.violations)
      .filter(isRecord)
      .map((entry) => ({
        kind: strOrNull(entry.kind) ?? '',
        detail: strOrNull(entry.detail) ?? ''
      })),
    physics: readPhysics(payload.physics)
  };
};
