import type { FieldMapPayload } from '@/jarvis/cards/payloads/payloadTypes';
import { isNum, isRecord, isStr, list, strOrNull } from '@/jarvis/cards/payloads/payloadPrimitives';

export const readFieldMap = (payload: unknown): FieldMapPayload | null => {
  if (!isRecord(payload)) {
    return null;
  }
  const edges = list(payload.edges)
    .filter((edge): edge is Record<string, unknown> => isRecord(edge))
    .filter((edge) => isStr(edge.injector) && isStr(edge.producer) && isNum(edge.weight))
    .map((edge) => ({
      injector: edge.injector as string,
      producer: edge.producer as string,
      weight: edge.weight as number
    }));
  return {
    focus: list(payload.focus).filter(isStr),
    highlight: list(payload.highlight).filter(isStr),
    edges,
    layer: strOrNull(payload.layer)
  };
};
