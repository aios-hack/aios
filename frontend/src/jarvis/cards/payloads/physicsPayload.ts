import type { PhysicsCheck, PhysicsPayload } from '@/jarvis/cards/payloads/systemTypes';
import { boolOrNull } from '@/jarvis/cards/payloads/scalars';
import { isRecord, isStr, list, numOrNull, strOrNull } from '@/jarvis/cards/payloads/payloadPrimitives';

const physicsCheck = (value: unknown): PhysicsCheck | null => {
  if (!isRecord(value)) {
    return null;
  }
  const id = strOrNull(value.id);
  if (id === null) {
    return null;
  }
  return { id, status: strOrNull(value.status) ?? 'ok', detail: strOrNull(value.detail) };
};

export const readPhysics = (payload: unknown): PhysicsPayload | null => {
  if (!isRecord(payload)) {
    return null;
  }
  return {
    run_id: isStr(payload.run_id) ? payload.run_id : '',
    admissible: boolOrNull(payload.admissible),
    blocking: numOrNull(payload.blocking),
    warnings: numOrNull(payload.warnings),
    checks: list(payload.checks)
      .map(physicsCheck)
      .filter((check): check is PhysicsCheck => check !== null)
  };
};
