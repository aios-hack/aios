import { memo, useMemo } from 'react';
import { MIN_RADIUS, type WellState } from '../shared/wellState';
import { ringStroke, SelectionRings } from '../shared/SelectionRings';
import type { SelectionHighlight } from '../WellCard/useSelectionHighlight';
import type { PlacedNode } from './interpolate';

const markerPath = (x: number, y: number, r: number): string =>
  `M ${x} ${y + r * 1.25} L ${x + r * 1.1} ${y - r * 0.85} L ${x - r * 1.1} ${y - r * 0.85} Z`;

export const HALO_GAP = 0.85;
const STROKE_WIDTH = 0.18;
const HOLLOW_STROKE_WIDTH = 0.28;

export const GLYPH_SCALE = 0.62;

const DIMMED_OPACITY = 0.25;
export const FADED_OPACITY = 0.12;
export const SELECTED_SCALE = 1.15;

export const TAP_MIN_PX = 44;

export const hitRadius = (
  drawnRadius: number,
  unitsPerPixel: number,
  gap: number
): number => {
  const comfortable = (TAP_MIN_PX / 2) * unitsPerPixel;
  const crowdCap = gap > 0 ? gap / 2 : comfortable;
  return Math.max(drawnRadius, Math.min(comfortable, crowdCap));
};

export const nearestGaps = (placed: PlacedNode[]): Map<string, number> => {
  const gaps = new Map<string, number>();
  for (const node of placed) {
    let best = Number.POSITIVE_INFINITY;
    for (const other of placed) {
      if (other.id === node.id) {
        continue;
      }
      const dx = other.x - node.x;
      const dy = other.y - node.y;
      const distance = Math.sqrt(dx * dx + dy * dy);
      if (distance < best) {
        best = distance;
      }
    }
    gaps.set(node.id, Number.isFinite(best) ? best : 0);
  }
  return gaps;
};

export const nodeOpacity = (
  presence: number,
  mark: string,
  dimmed: boolean
): number => {
  if (mark === 'faded') {
    return presence * FADED_OPACITY;
  }
  return presence * (dimmed ? DIMMED_OPACITY : 1);
};

interface NodeLayerProps {
  placed: PlacedNode[];
  states: Map<string, WellState>;
  selectedWell: string | null;
  highlight: SelectionHighlight;
  titleOf: (node: PlacedNode) => string;
  scale: number;
  unitsPerPixel: number;
  isDimmed: (id: string) => boolean;
  onSelectWell: (well: string) => void;
}

const NodeLayerView = ({
  placed,
  states,
  selectedWell,
  highlight,
  titleOf,
  scale,
  unitsPerPixel,
  isDimmed,
  onSelectWell
}: NodeLayerProps) => {
  const gaps = useMemo(() => nearestGaps(placed), [placed]);
  return (
  <g className="field-projection-nodes">
    {placed.map((node) => {
      const state = states.get(node.id) ?? null;
      const selected = node.id === selectedWell;
      const baseRadius =
        ((state === null ? MIN_RADIUS : state.radius) * GLYPH_SCALE) / scale;
      const radius = selected ? baseRadius * SELECTED_SCALE : baseRadius;
      const fill = state === null || state.fill === null ? 'none' : state.fill;
      const stroke = state === null ? 'var(--color-well-dim)' : state.stroke;
      const strokeWidth =
        (state !== null && state.hollow ? HOLLOW_STROKE_WIDTH : STROKE_WIDTH) / scale;
      const status =
        state === null
          ? 'unknown'
          : !state.commissioned
            ? 'not-commissioned'
            : state.hollow
              ? 'shut'
              : 'open';
      const mark = highlight.stateOf(node.id);
      const dimmed = isDimmed(node.id);
      return (
        <g
          key={node.id}
          className="field-projection-node"
          data-well-id={node.id}
          data-x={node.x}
          data-y={node.y}
          data-presence={node.presence}
          data-status={status}
          data-selected={selected}
          data-highlight={mark}
          data-only-map={node.onlyMap}
          data-active={!dimmed}
          opacity={nodeOpacity(node.presence, mark, dimmed)}
          tabIndex={0}
          role="button"
          aria-label={node.id}
          onClick={() => onSelectWell(node.id)}
          onKeyDown={(event) => {
            if (event.key === 'Enter' || event.key === ' ') {
              event.preventDefault();
              onSelectWell(node.id);
            }
          }}
        >
          <circle
            className="field-projection-hit"
            cx={node.x}
            cy={node.y}
            r={hitRadius(radius, unitsPerPixel, gaps.get(node.id) ?? 0)}
            fill="transparent"
            stroke="none"
          />
          {mark !== 'plain' && (
            <SelectionRings
              x={node.x}
              y={node.y}
              r={radius}
              scale={scale}
              state={mark}
              groupColor={highlight.groupColorOf(node.id)}
            />
          )}
          {selected && (
            <circle
              className="field-projection-halo"
              cx={node.x}
              cy={node.y}
              r={radius + HALO_GAP / scale}
              fill="none"
              stroke="var(--color-oil-strong)"
              strokeWidth={ringStroke(radius, 1)}
            />
          )}
          {state !== null && state.row.role === 'INJ' ? (
            <path
              className="field-projection-glyph"
              d={markerPath(node.x, node.y, radius)}
              fill={fill}
              stroke={stroke}
              strokeWidth={strokeWidth}
            />
          ) : (
            <circle
              className="field-projection-glyph"
              cx={node.x}
              cy={node.y}
              r={radius}
              fill={fill}
              stroke={stroke}
              strokeWidth={strokeWidth}
            />
          )}
          <title>{titleOf(node)}</title>
        </g>
      );
    })}
  </g>
  );
};

export const NodeLayer = memo(NodeLayerView);
