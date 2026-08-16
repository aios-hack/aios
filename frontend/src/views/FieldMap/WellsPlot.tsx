import type { GridSize, WellPoint } from '../../api/types';
import { useT } from '../../i18n/I18nContext';
import { fluidColors, layerColors } from '../../theme/tokens';
import type { LayerFilter } from './LayerSwitch';
import { PlotAxes } from './PlotAxes';
import type { WellRole } from './roles';

const PAD_LEFT = 16;
const PAD_TOP = 12;
const PAD_RIGHT = 18;
const PAD_BOTTOM = 18;
const R = 1.4;

export const wellColor = (layers: number[]): string => {
  if (layers.length > 1) {
    return layerColors.both;
  }
  return layers[0] === 2 ? layerColors.layer2 : layerColors.layer1;
};

const markerPath = (x: number, y: number, r: number): string =>
  `M ${x} ${y + r * 1.25} L ${x + r * 1.1} ${y - r * 0.85} L ${x - r * 1.1} ${y - r * 0.85} Z`;

interface WellsPlotProps {
  wells: WellPoint[];
  grid: GridSize;
  filter: LayerFilter;
  roles: Map<string, WellRole>;
  selectedWell: string | null;
  onSelectWell: (well: string) => void;
}

export const WellsPlot = ({
  wells,
  grid,
  filter,
  roles,
  selectedWell,
  onSelectWell
}: WellsPlotProps) => {
  const t = useT();

  return (
    <svg
      className="wells-plot"
      viewBox={`${-PAD_LEFT} ${-PAD_TOP} ${grid.ni + PAD_LEFT + PAD_RIGHT} ${grid.nj + PAD_TOP + PAD_BOTTOM}`}
      role="img"
      aria-label={t('map.ariaLabel')}
    >
      <defs>
        <pattern id="map-grid" width="10" height="10" patternUnits="userSpaceOnUse">
          <path
            d="M 10 0 L 0 0 0 10"
            fill="none"
            stroke="var(--color-border)"
            strokeWidth={0.15}
          />
        </pattern>
      </defs>
      <rect x={0} y={0} width={grid.ni} height={grid.nj} fill="url(#map-grid)" />
      <PlotAxes grid={grid} axisI={t('map.axisI')} axisJ={t('map.axisJ')} />
      {wells.map((well) => {
        const active = filter === 'all' || well.layers.includes(filter);
        const selected = well.id === selectedWell;
        const role = roles.get(well.id) ?? null;
        const fill = active ? wellColor(well.layers) : layerColors.dim;
        return (
          <g
            key={well.id}
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
      })}
    </svg>
  );
};
