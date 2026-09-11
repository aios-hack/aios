import type {
  SystemEdge,
  SystemMapPayload,
  SystemNode
} from '@/jarvis/cards/payloads/systemTypes';
import { isNum, isRecord, isStr, list, strOrNull } from '@/jarvis/cards/payloads/payloadPrimitives';

const systemNode = (value: unknown): SystemNode | null => {
  if (!isRecord(value) || !isStr(value.id)) {
    return null;
  }
  return {
    id: value.id,
    label: strOrNull(value.label) ?? value.id,
    kind: isStr(value.kind) ? value.kind : 'service',
    summary: strOrNull(value.summary) ?? '',
    doc: strOrNull(value.doc),
    route: strOrNull(value.route),
    files: list(value.files).filter(isStr)
  };
};

const systemEdge = (value: unknown): SystemEdge | null => {
  if (!isRecord(value) || !isStr(value.from) || !isStr(value.to)) {
    return null;
  }
  return { from: value.from, to: value.to, label: strOrNull(value.label) ?? '' };
};

export const readSystemMap = (payload: unknown): SystemMapPayload | null => {
  if (!isRecord(payload)) {
    return null;
  }
  const nodes = list(payload.nodes)
    .map(systemNode)
    .filter((entry): entry is SystemNode => entry !== null);
  if (nodes.length === 0) {
    return null;
  }
  return {
    focus: strOrNull(payload.focus),
    nodes,
    edges: list(payload.edges)
      .map(systemEdge)
      .filter((entry): entry is SystemEdge => entry !== null),
    total_nodes: isNum(payload.total_nodes) ? payload.total_nodes : nodes.length,
    total_edges: isNum(payload.total_edges) ? payload.total_edges : 0
  };
};
