import type { GraphEdge, GraphFile } from '../../api/types';

export interface LambdaNeighbour {
  well: string;
  weight: number;
  role: 'INJ' | 'PROD';
}

export interface WellConnectivity {
  group: string | null;
  inGraph: boolean;
  neighbours: LambdaNeighbour[];
  threshold: number;
  window: GraphFile['window'];
}

export const neighbourThreshold = (edges: GraphEdge[]): number => {
  if (edges.length === 0) {
    return 0;
  }
  return Math.min(...edges.map((edge) => Math.abs(edge.weight)));
};

export const connectivityOf = (
  well: string,
  data: GraphFile,
  threshold: number
): WellConnectivity => {
  const node = data.nodes.find((item) => item.id === well) ?? null;
  const neighbours: LambdaNeighbour[] = [];
  for (const edge of data.edges) {
    if (Math.abs(edge.weight) < threshold) {
      continue;
    }
    if (edge.producer === well) {
      neighbours.push({ well: edge.injector, weight: edge.weight, role: 'INJ' });
    } else if (edge.injector === well) {
      neighbours.push({ well: edge.producer, weight: edge.weight, role: 'PROD' });
    }
  }
  neighbours.sort((a, b) => Math.abs(b.weight) - Math.abs(a.weight));
  return {
    group: node?.group ?? null,
    inGraph: node !== null,
    neighbours,
    threshold,
    window: data.window
  };
};
