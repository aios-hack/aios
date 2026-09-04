import { memo, useMemo } from 'react';
import type { GraphEdge } from '../../api/types';
import { edgeColors } from '../../theme/tokens';
import { edgeOpacity, edgeStrength, edgeWidth } from '../shared/graphModel';
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

interface EdgeStyle {
  edge: GraphEdge;
  id: string;
  baseOpacity: number;
  relation: EdgeRelation;
  strength: number;
  width: number;
  stroke: string;
}

const edgeStyles = (
  edges: GraphEdge[],
  maxWeight: number,
  scale: number,
  selectedWell: string | null
): EdgeStyle[] =>
  edges.map((edge) => {
    const relation = edgeRelation(edge, selectedWell);
    const width = edgeWidth(edge.weight, maxWeight) / scale;
    return {
      edge,
      id: `${edge.injector}-${edge.producer}`,
      baseOpacity: edgeOpacity(edge.weight, maxWeight),
      relation,
      strength: edgeStrength(edge.weight, maxWeight),
      width: relation === 'linked' ? width * EDGE_LINKED_BOOST : width,
      stroke: edge.weight >= 0 ? edgeColors.positive : edgeColors.negative
    };
  });

const relativeOpacity = (base: number, relation: EdgeRelation): number => {
  if (relation === 'muted') {
    return base * EDGE_MUTED_SHARE;
  }
  if (relation === 'linked') {
    return Math.min(base * EDGE_LINKED_BOOST, 1);
  }
  return base;
};

const EdgeLayerView = ({
  edges,
  placed,
  maxWeight,
  t,
  scale,
  selectedWell
}: EdgeLayerProps) => {
  const styles = useMemo(
    () => edgeStyles(edges, maxWeight, scale, selectedWell),
    [edges, maxWeight, scale, selectedWell]
  );
  return (
    <g className="field-projection-edges" data-testid="field-projection-edges" data-t={t}>
      {styles.map((style) => {
        const from = placed.get(style.edge.injector);
        const to = placed.get(style.edge.producer);
        if (from === undefined || to === undefined) {
          return null;
        }
        const opacity = relativeOpacity(
          edgeOpacityAt(t, style.baseOpacity),
          style.relation
        );
        return (
          <line
            key={style.id}
            x1={from.x}
            y1={from.y}
            x2={to.x}
            y2={to.y}
            stroke={style.stroke}
            strokeWidth={style.width}
            strokeOpacity={opacity}
            strokeLinecap="round"
            data-edge-id={style.id}
            data-opacity={opacity}
            data-relation={style.relation}
            data-strength={style.strength}
          />
        );
      })}
    </g>
  );
};

export const EdgeLayer = memo(EdgeLayerView);
