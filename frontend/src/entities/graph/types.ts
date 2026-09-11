import type { ArtifactMeta } from '@/shared/api/artifact';

export interface GraphNode {
  id: string;
  role: 'INJ' | 'PROD';
  group: string | null;
  x: number;
  y: number;
}

export interface GraphEdge {
  injector: string;
  producer: string;
  weight: number;
}

export interface GraphGroup {
  id: string;
  wells: string[];
}

export interface GraphWindow {
  start: string;
  end: string;
}

export interface GraphMeta {
  lag_months: number;
  amplitude: number;
  stability: number;
  rank: number;
  condition_number: number;
}

export interface GraphFile {
  window: GraphWindow;
  nodes: GraphNode[];
  edges: GraphEdge[];
  groups: GraphGroup[];
  weight_range: { min: number; max: number };
  meta: GraphMeta & Partial<ArtifactMeta>;
  layout: { size: number; seed: number };
}
