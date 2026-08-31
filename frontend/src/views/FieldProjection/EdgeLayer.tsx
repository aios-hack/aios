import { memo } from 'react';
import type { GraphEdge } from '../../api/types';
import { edgeOpacity, edgeWidth } from '../shared/graphModel';
import { edgeOpacityAt, type PlacedNode } from './interpolate';

export const EDGE_MUTED_SHARE = 0.18;
export const EDGE_LINKED_BOOST = 1.45;

interface EdgeLayerProps {
  edges: GraphEdge[];
  placed: Map<string, PlacedNode>;
  maxWeight: number;
  t: number;
  scale: number;
  selectedWell: string | null;
}

export type EdgeRelation = 'plain' | 'linked' | 'muted';

export const edgeRelation = (
  edge: GraphEdge,
  selectedWell: string | null
): EdgeRelation => {
  if (selectedWell === null) {
    return 'plain';
  }
  return edge.injector === selectedWell || edge.producer === selectedWell
    ? 'linked'
    : 'muted';
};

const EdgeLayerView = ({
  edges,
  placed,
  maxWeight,
  t,
  scale,
  selectedWell
}: EdgeLayerProps) => (
  <g className="field-projection-edges" data-testid="field-projection-edges" data-t={t}>
    {edges.map((edge) => {
      const from = placed.get(edge.injector);
      const to = placed.get(edge.producer);
      if (from === undefined || to === undefined) {
        return null;
      }
      const base = edgeOpacityAt(t, edgeOpacity(edge.weight, maxWeight));
      const relation = edgeRelation(edge, selectedWell);
      const opacity =
        relation === 'muted'
          ? base * EDGE_MUTED_SHARE
          : relation === 'linked'
            ? Math.min(base * EDGE_LINKED_BOOST, 1)
            : base;
      const width = edgeWidth(edge.weight, maxWeight) / scale;
      return (
        <line
          key={`${edge.injector}-${edge.producer}`}
          x1={from.x}
          y1={from.y}
          x2={to.x}
          y2={to.y}
          stroke={
            edge.weight >= 0
              ? 'var(--color-edge-positive)'
              : 'var(--color-edge-negative)'
          }
          strokeWidth={relation === 'linked' ? width * EDGE_LINKED_BOOST : width}
          strokeOpacity={opacity}
          strokeLinecap="round"
          data-edge-id={`${edge.injector}-${edge.producer}`}
          data-opacity={opacity}
          data-relation={relation}
        />
      );
    })}
  </g>
);

export const EdgeLayer = memo(EdgeLayerView);
