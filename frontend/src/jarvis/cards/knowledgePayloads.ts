import type { GlossaryPayload, GuidePayload } from './payloadTypes';
import { isRecord, isStr, list, strOrNull, textOf } from './payloadPrimitives';

export const readGlossary = (payload: unknown): GlossaryPayload | null => {
  if (!isRecord(payload) || !isStr(payload.id)) {
    return null;
  }
  const term = textOf(payload.term);
  const definition = textOf(payload.definition);
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
        what: textOf(entry.what) ?? '',
        spotlight: strOrNull(entry.spotlight)
      })),
    related: list(payload.related).filter(isStr)
  };
};

export const readGuide = (payload: unknown): GuidePayload | null => {
  if (!isRecord(payload) || !isStr(payload.workspace) || !isStr(payload.view)) {
    return null;
  }
  const title = textOf(payload.title);
  const what = textOf(payload.what);
  if (title === null || what === null) {
    return null;
  }
  return {
    workspace: payload.workspace,
    view: payload.view,
    title,
    what,
    how_to_read: textOf(payload.how_to_read) ?? '',
    controls: list(payload.controls)
      .filter((entry): entry is Record<string, unknown> => isRecord(entry))
      .map((entry) => ({
        label: textOf(entry.label) ?? '',
        spotlight: strOrNull(entry.spotlight),
        hotkey: strOrNull(entry.hotkey)
      })),
    questions: list(payload.questions).filter(isStr)
  };
};
