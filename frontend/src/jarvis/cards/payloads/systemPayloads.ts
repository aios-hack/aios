import type {
  DocHit,
  DocPayload,
  StatusBoardPayload,
  SystemEdge,
  SystemMapPayload,
  SystemNode
} from '@/jarvis/cards/payloads/systemTypes';
import { boolOrNull } from '@/jarvis/cards/payloads/scalars';
import { isNum, isRecord, isStr, list, numOrNull, strOrNull, textOf } from '@/jarvis/cards/payloads/payloadPrimitives';

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

const systemNode = (value: unknown, lang: string): SystemNode | null => {
  if (!isRecord(value) || !isStr(value.id)) {
    return null;
  }
  return {
    id: value.id,
    label: textOf(value.label, lang) ?? value.id,
    kind: isStr(value.kind) ? value.kind : 'service',
    summary: textOf(value.summary, lang) ?? '',
    doc: strOrNull(value.doc),
    route: strOrNull(value.route),
    files: list(value.files).filter(isStr)
  };
};

const systemEdge = (value: unknown, lang: string): SystemEdge | null => {
  if (!isRecord(value) || !isStr(value.from) || !isStr(value.to)) {
    return null;
  }
  return { from: value.from, to: value.to, label: textOf(value.label, lang) ?? '' };
};

export const readSystemMap = (payload: unknown, lang: string): SystemMapPayload | null => {
  if (!isRecord(payload)) {
    return null;
  }
  const nodes = list(payload.nodes)
    .map((entry) => systemNode(entry, lang))
    .filter((entry): entry is SystemNode => entry !== null);
  if (nodes.length === 0) {
    return null;
  }
  return {
    focus: strOrNull(payload.focus),
    nodes,
    edges: list(payload.edges)
      .map((entry) => systemEdge(entry, lang))
      .filter((entry): entry is SystemEdge => entry !== null),
    total_nodes: isNum(payload.total_nodes) ? payload.total_nodes : nodes.length,
    total_edges: isNum(payload.total_edges) ? payload.total_edges : 0
  };
};

export const readStatusBoard = (payload: unknown): StatusBoardPayload | null => {
  if (!isRecord(payload)) {
    return null;
  }
  const champion = isRecord(payload.champion) ? payload.champion : {};
  const last = isRecord(payload.last_run) ? payload.last_run : {};
  return {
    champion: {
      recorded: champion.recorded === true,
      npv: numOrNull(champion.opm_npv_rub),
      sound: boolOrNull(champion.sound),
      ood: numOrNull(champion.ood_score),
      reason: strOrNull(champion.reason)
    },
    last_run: {
      recorded: last.recorded === true,
      run_id: strOrNull(last.run_id),
      status: strOrNull(last.status),
      verified_npv: numOrNull(last.verified_npv),
      predicted_npv: numOrNull(last.predicted_npv),
      reason: strOrNull(last.reason)
    },
    scenario: isStr(payload.scenario) ? payload.scenario : '',
    step: isNum(payload.step) ? payload.step : 0,
    date: strOrNull(payload.date),
    data: isStr(payload.data) ? payload.data : '',
    alerts: list(payload.alerts)
      .filter(isRecord)
      .map((row) => ({
        pattern: strOrNull(row.pattern),
        name: strOrNull(row.name),
        well: strOrNull(row.well),
        severity: strOrNull(row.severity),
        step: numOrNull(row.step)
      }))
  };
};
