import type { SystemEdge, SystemNode } from '@/jarvis/cards/payloads/payloadTypes';

export interface MapPlace {
  id: string;
  x: number;
  y: number;
}

export const VIEW_W = 100;
export const VIEW_H = 62;

const KIND_ROW: Record<string, number> = {
  ui: 0,
  service: 1,
  domain: 2,
  infra: 3,
  data: 4,
  doc: 5
};

export const rowOf = (kind: string): number => KIND_ROW[kind] ?? 1;

export const placeNodes = (nodes: readonly SystemNode[]): MapPlace[] => {
  const rows = new Map<number, SystemNode[]>();
  for (const node of nodes) {
    const row = rowOf(node.kind);
    const bucket = rows.get(row);
    if (bucket === undefined) {
      rows.set(row, [node]);
      continue;
    }
    bucket.push(node);
  }
  const used = [...rows.keys()].sort((a, b) => a - b);
  const places: MapPlace[] = [];
  used.forEach((row, rowIndex) => {
    const bucket = rows.get(row) ?? [];
    const y = ((rowIndex + 1) / (used.length + 1)) * VIEW_H;
    bucket.forEach((node, column) => {
      places.push({
        id: node.id,
        x: ((column + 1) / (bucket.length + 1)) * VIEW_W,
        y
      });
    });
  });
  return places;
};

export const edgeLine = (
  places: readonly MapPlace[],
  edge: SystemEdge
): { x1: number; y1: number; x2: number; y2: number } | null => {
  const from = places.find((place) => place.id === edge.from);
  const to = places.find((place) => place.id === edge.to);
  if (from === undefined || to === undefined) {
    return null;
  }
  return { x1: from.x, y1: from.y, x2: to.x, y2: to.y };
};
