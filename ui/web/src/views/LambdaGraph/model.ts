import type { GraphEdge, GraphFile, GraphNode } from '../../api/types';

export interface Selection {
  well: string;
  group: string | null;
  members: Set<string>;
  neighbours: Set<string>;
}

export interface WellFluidState {
  watercut: number | null;
  commissioned: boolean;
}

export const isGraphFile = (data: unknown): data is GraphFile => {
  if (typeof data !== 'object' || data === null) {
    return false;
  }
  const candidate = data as Partial<GraphFile>;
  return (
    Array.isArray(candidate.nodes) &&
    candidate.nodes.length > 0 &&
    Array.isArray(candidate.edges) &&
    typeof candidate.window === 'object' &&
    candidate.window !== null &&
    typeof candidate.window.start === 'string' &&
    typeof candidate.window.end === 'string'
  );
};

export const groupIndex = (data: GraphFile): Map<string, number> =>
  new Map(data.groups.map((group, index) => [group.id, index]));

export const visibleEdges = (edges: GraphEdge[], threshold: number): GraphEdge[] =>
  edges.filter((edge) => Math.abs(edge.weight) >= threshold);

export const edgeOpacity = (weight: number, max: number): number => {
  if (max <= 0) {
    return 1;
  }
  return 0.25 + 0.65 * (Math.abs(weight) / max);
};

export const edgeWidth = (weight: number, max: number): number => {
  if (max <= 0) {
    return 0.4;
  }
  return 0.3 + 1.5 * (Math.abs(weight) / max);
};

export const buildSelection = (
  well: string,
  data: GraphFile,
  threshold: number
): Selection => {
  const node = data.nodes.find((item) => item.id === well) ?? null;
  const group = node?.group ?? null;
  const members = new Set<string>();
  if (group !== null) {
    const found = data.groups.find((item) => item.id === group);
    for (const member of found?.wells ?? []) {
      members.add(member);
    }
  }
  const neighbours = new Set<string>();
  for (const edge of visibleEdges(data.edges, threshold)) {
    if (edge.injector === well) {
      neighbours.add(edge.producer);
    } else if (edge.producer === well) {
      neighbours.add(edge.injector);
    }
  }
  return { well, group, members, neighbours };
};

export const nodeState = (
  node: GraphNode,
  selection: Selection | null
): 'selected' | 'neighbour' | 'group' | 'plain' | 'faded' => {
  if (selection === null) {
    return 'plain';
  }
  if (node.id === selection.well) {
    return 'selected';
  }
  if (selection.neighbours.has(node.id)) {
    return 'neighbour';
  }
  if (selection.members.has(node.id)) {
    return 'group';
  }
  return 'faded';
};

export const edgeHighlighted = (edge: GraphEdge, selection: Selection | null): boolean =>
  selection !== null &&
  (edge.injector === selection.well || edge.producer === selection.well);

export const formatWindowDate = (iso: string): string => {
  const [year, month, day] = iso.split('-');
  if (!year || !month || !day) {
    return iso;
  }
  return `${day}.${month}.${year}`;
};

export const roundWeight = (weight: number): string => weight.toFixed(3);
