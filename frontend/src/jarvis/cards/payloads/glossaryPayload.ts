import type { GlossaryPayload } from '@/jarvis/cards/payloads/payloadTypes';
import { isRecord, isStr, list, strOrNull } from '@/jarvis/cards/payloads/payloadPrimitives';

export const readGlossary = (payload: unknown): GlossaryPayload | null => {
  if (!isRecord(payload) || !isStr(payload.id)) {
    return null;
  }
  const term = strOrNull(payload.term);
  const definition = strOrNull(payload.definition);
  if (term === null || definition === null) {
    return null;
  }
  return {
    id: payload.id,
    term,
    definition,
    formula: strOrNull(payload.formula),
    unit: strOrNull(payload.unit),
    source: strOrNull(payload.source),
    where_in_platform: list(payload.where_in_platform)
      .filter((entry): entry is Record<string, unknown> => isRecord(entry))
      .filter((entry) => isStr(entry.workspace) && isStr(entry.view))
      .map((entry) => ({
        workspace: entry.workspace as string,
        view: entry.view as string,
        what: strOrNull(entry.what) ?? '',
        spotlight: strOrNull(entry.spotlight)
      })),
    related: list(payload.related).filter(isStr)
  };
};
