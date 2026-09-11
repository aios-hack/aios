import type { DocHit, DocPayload } from '@/jarvis/cards/payloads/systemTypes';
import { isNum, isRecord, isStr, list, numOrNull, strOrNull } from '@/jarvis/cards/payloads/payloadPrimitives';

const docHit = (value: unknown): DocHit | null => {
  if (!isRecord(value) || !isStr(value.source)) {
    return null;
  }
  return {
    source: value.source,
    heading: isStr(value.heading) ? value.heading : '',
    anchor: strOrNull(value.anchor),
    snippet: isStr(value.snippet) ? value.snippet : '',
    text: isStr(value.text) ? value.text : '',
    score: numOrNull(value.score),
    numbers: list(value.numbers).filter(isNum),
    scope: strOrNull(value.scope)
  };
};

export const readDoc = (payload: unknown): DocPayload | null => {
  if (!isRecord(payload)) {
    return null;
  }
  const hits = list(payload.hits)
    .map(docHit)
    .filter((hit): hit is DocHit => hit !== null);
  if (hits.length === 0) {
    return null;
  }
  return {
    query: isStr(payload.query) ? payload.query : '',
    scope: isStr(payload.scope) ? payload.scope : 'all',
    terms: list(payload.terms).filter(isStr),
    hits,
    indexed_chunks: isNum(payload.indexed_chunks) ? payload.indexed_chunks : 0,
    indexed_files: isNum(payload.indexed_files) ? payload.indexed_files : 0
  };
};
