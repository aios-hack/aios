import { memo } from 'react';
import { MIN_RADIUS, type WellState } from '../shared/wellState';
import { SelectionRings } from '../shared/SelectionRings';
import type { SelectionHighlight } from '../WellCard/useSelectionHighlight';
import type { PlacedNode } from './interpolate';

const markerPath = (x: number, y: number, r: number): string =>
  `M ${x} ${y + r * 1.25} L ${x + r * 1.1} ${y - r * 0.85} L ${x - r * 1.1} ${y - r * 0.85} Z`;

const HALO_SCALE = 1.9;
const STROKE_WIDTH = 0.18;
const HOLLOW_STROKE_WIDTH = 0.28;

const DIMMED_OPACITY = 0.25;
const HIT_RADIUS_PX = 12;

interface NodeLayerProps {
  placed: PlacedNode[];
  states: Map<string, WellState>;
  selectedWell: string | null;
  highlight: SelectionHighlight;
  titleOf: (node: PlacedNode) => string;
  scale: number;
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
  isDimmed,
  onSelectWell
}: NodeLayerProps) => (
  <g className="field-projection-nodes">
    {placed.map((node) => {
      const state = states.get(node.id) ?? null;
      const radius = (state === null ? MIN_RADIUS : state.radius) / scale;
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
      const selected = node.id === selectedWell;
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
          opacity={node.presence * (mark === 'faded' ? 0.25 : dimmed ? DIMMED_OPACITY : 1)}
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
            r={Math.max(radius, HIT_RADIUS_PX / scale)}
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
              r={radius * HALO_SCALE}
              fill="none"
              stroke="var(--color-oil)"
              strokeWidth={0.35 / scale}
            />
          )}
          {state !== null && state.row.role === 'INJ' ? (
            <path
              d={markerPath(node.x, node.y, radius)}
              fill={fill}
              stroke={stroke}
              strokeWidth={strokeWidth}
            />
          ) : (
            <circle
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

export const NodeLayer = memo(NodeLayerView);
