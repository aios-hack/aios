import { memo } from 'react';
import type { WellPoint } from '../../api/types';
import { fluidColors, layerColors } from '../../theme/tokens';
import type { WellRole } from './roles';

const R = 1.4;

export const wellColor = (layers: number[]): string => {
  if (layers.length > 1) {
    return layerColors.both;
  }
  return layers[0] === 2 ? layerColors.layer2 : layerColors.layer1;
};

const markerPath = (x: number, y: number, r: number): string =>
  `M ${x} ${y + r * 1.25} L ${x + r * 1.1} ${y - r * 0.85} L ${x - r * 1.1} ${y - r * 0.85} Z`;

interface WellMarkerProps {
  well: WellPoint;
  active: boolean;
  selected: boolean;
  role: WellRole | null;
  onSelectWell: (well: string) => void;
}

const WellMarkerView = ({
  well,
  active,
  selected,
  role,
  onSelectWell
}: WellMarkerProps) => {
  const fill = active ? wellColor(well.layers) : layerColors.dim;

  return (
    <g
      className="wells-plot-well"
      data-well-id={well.id}
      data-active={active}
      data-selected={selected}
      tabIndex={0}
      role="button"
      aria-label={well.id}
      onClick={() => onSelectWell(well.id)}
      onKeyDown={(event) => {
        if (event.key === 'Enter' || event.key === ' ') {
          event.preventDefault();
          onSelectWell(well.id);
        }
      }}
    >
      {selected && (
        <circle
          className="wells-plot-halo"
          cx={well.i}
          cy={well.j}
          r={R * 1.9}
          fill="none"
          stroke={fluidColors.oil}
          strokeWidth={0.35}
        />
      )}
      {role === 'INJ' ? (
        <path
          d={markerPath(well.i, well.j, active ? R : R * 0.7)}
          fill={fill}
          stroke="var(--color-surface-solid)"
          strokeWidth={0.18}
        />
      ) : (
        <circle
          cx={well.i}
          cy={well.j}
          r={active ? R : R * 0.7}
          fill={fill}
          stroke="var(--color-surface-solid)"
          strokeWidth={0.18}
        />
      )}
      <title>{`${well.id} · I ${well.i}, J ${well.j}`}</title>
    </g>
  );
};

export const WellMarker = memo(WellMarkerView);
