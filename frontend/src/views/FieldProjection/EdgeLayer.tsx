import { memo } from 'react';
import type { GraphEdge } from '../../api/types';
import { edgeOpacity, edgeWidth } from '../shared/graphModel';
import { edgeOpacityAt, type PlacedNode } from './interpolate';

interface EdgeLayerProps {
  edges: GraphEdge[];
  placed: Map<string, PlacedNode>;
  maxWeight: number;
  t: number;
  scale: number;
}

const EdgeLayerView = ({ edges, placed, maxWeight, t, scale }: EdgeLayerProps) => (
  <g className="field-projection-edges" data-testid="field-projection-edges" data-t={t}>
    {edges.map((edge) => {
      const from = placed.get(edge.injector);
      const to = placed.get(edge.producer);
      if (from === undefined || to === undefined) {
        return null;
      }
      const opacity = edgeOpacityAt(t, edgeOpacity(edge.weight, maxWeight));
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
          strokeWidth={edgeWidth(edge.weight, maxWeight) / scale}
          strokeOpacity={opacity}
          strokeLinecap="round"
          data-edge-id={`${edge.injector}-${edge.producer}`}
          data-opacity={opacity}
        />
      );
    })}
  </g>
);

export const EdgeLayer = memo(EdgeLayerView);
