import type { GuidePayload } from '@/jarvis/cards/payloads/payloadTypes';
import { isRecord, isStr, list, strOrNull } from '@/jarvis/cards/payloads/payloadPrimitives';

export const readGuide = (payload: unknown): GuidePayload | null => {
  if (!isRecord(payload) || !isStr(payload.workspace) || !isStr(payload.view)) {
    return null;
  }
  const title = strOrNull(payload.title);
  const what = strOrNull(payload.what);
  if (title === null || what === null) {
    return null;
  }
  return {
    workspace: payload.workspace,
    view: payload.view,
    title,
    what,
    how_to_read: strOrNull(payload.how_to_read) ?? '',
    controls: list(payload.controls)
      .filter((entry): entry is Record<string, unknown> => isRecord(entry))
      .map((entry) => ({
        label: strOrNull(entry.label) ?? '',
        spotlight: strOrNull(entry.spotlight),
        hotkey: strOrNull(entry.hotkey)
      })),
    questions: list(payload.questions).filter(isStr)
  };
};
