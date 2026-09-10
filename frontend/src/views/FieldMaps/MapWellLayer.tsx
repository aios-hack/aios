import { useCallback } from 'react';
import type { MapWell, TimelineWellRow } from '../../api/types';
import { clamp01, ratioColor } from '../../theme/scales';

export const WELL_RADIUS = 1.15;
export const SELECTED_SCALE = 1.6;

export interface WellPlacement {
  well: MapWell;
  x: number;
  y: number;
}

export const bhpShare = (
  bhp: number,
  bounds: { min: number; max: number }
): number => {
  const span = bounds.max - bounds.min;
  if (span <= 0 || !Number.isFinite(bhp)) {
    return 0;
  }
  return clamp01((bhp - bounds.min) / span);
};

export const bhpBounds = (
  rows: Map<string, TimelineWellRow>
): { min: number; max: number } => {
  let min = Number.POSITIVE_INFINITY;
  let max = Number.NEGATIVE_INFINITY;
  for (const row of rows.values()) {
    if (!Number.isFinite(row.bhp) || row.bhp <= 0) {
      continue;
    }
    min = Math.min(min, row.bhp);
    max = Math.max(max, row.bhp);
  }
  if (min > max) {
    return { min: 0, max: 0 };
  }
  return { min, max };
};

interface MapWellLayerProps {
  placements: readonly WellPlacement[];
  rows: Map<string, TimelineWellRow>;
  bounds: { min: number; max: number };
  selectedWell: string | null;
  showLabels: boolean;
  scale: number;
  onSelectWell: (well: string) => void;
  onHoverWell: (well: string | null) => void;
}

export const MapWellLayer = ({
  placements,
  rows,
  bounds,
  selectedWell,
  showLabels,
  scale,
  onSelectWell,
  onHoverWell
}: MapWellLayerProps) => {
  const radius = WELL_RADIUS / Math.max(scale, 0.2);
  const stroke = radius * 0.34;

  const fillOf = useCallback(
    (row: TimelineWellRow | undefined): string => {
      if (row === undefined || row.availability === 'NOT_COMMISSIONED') {
        return 'var(--color-well-dim)';
      }
      if (row.operating_status === 'SHUT') {
        return 'var(--color-map-well-shut)';
      }
      return ratioColor(bhpShare(row.bhp, bounds));
    },
    [bounds]
  );

  return (
    <g className="field-maps-wells" data-testid="field-maps-wells">
      {placements.map(({ well, x, y }) => {
        const row = rows.get(well.id);
        const selected = selectedWell === well.id;
        const size = selected ? radius * SELECTED_SCALE : radius;
        const watercut = row?.watercut;
        const shut = row !== undefined && row.operating_status === 'SHUT';
        return (
          <g
            key={well.id}
            className="field-maps-well"
            data-well={well.id}
            data-shut={shut ? 'true' : 'false'}
            data-selected={selected ? 'true' : 'false'}
            transform={`translate(${x} ${y})`}
            onPointerEnter={() => onHoverWell(well.id)}
            onPointerLeave={() => onHoverWell(null)}
            onClick={(event) => {
              event.stopPropagation();
              onSelectWell(well.id);
            }}
          >
            {row?.role === 'INJ' ? (
              <rect
                x={-size}
                y={-size}
                width={size * 2}
                height={size * 2}
                fill={fillOf(row)}
                stroke="var(--color-map-well)"
                strokeWidth={stroke}
              />
            ) : (
              <circle
                r={size}
                fill={fillOf(row)}
                stroke="var(--color-map-well)"
                strokeWidth={stroke}
              />
            )}
            {watercut !== null && watercut !== undefined && watercut > 0 && (
              <circle
                r={size + stroke * 1.6}
                fill="none"
                stroke="var(--scale-watercut-1)"
                strokeWidth={stroke}
                strokeOpacity={clamp01(watercut)}
                data-testid={`field-maps-watercut-${well.id}`}
              />
            )}
            {selected && (
              <circle
                r={size + stroke * 4}
                fill="none"
                stroke="var(--color-accent)"
                strokeWidth={stroke * 1.4}
              />
            )}
            {showLabels && (
              <text
                className="field-maps-well-label"
                x={size + stroke * 3}
                y={size * 0.6}
                fontSize={radius * 1.9}
              >
                {well.id}
              </text>
            )}
          </g>
        );
      })}
    </g>
  );
};
