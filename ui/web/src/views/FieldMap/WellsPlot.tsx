import type { GridSize, WellPoint } from '../../api/types';
import { useT } from '../../i18n/I18nContext';
import { layerColors, mapColors } from '../../theme/tokens';
import type { LayerFilter } from './LayerSwitch';

const PAD = 6;

export const wellColor = (layers: number[]): string => {
  if (layers.length > 1) {
    return layerColors.both;
  }
  return layers[0] === 2 ? layerColors.layer2 : layerColors.layer1;
};

interface WellsPlotProps {
  wells: WellPoint[];
  grid: GridSize;
  filter: LayerFilter;
  selectedWell: string | null;
  onSelectWell: (well: string) => void;
}

export const WellsPlot = ({
  wells,
  grid,
  filter,
  selectedWell,
  onSelectWell
}: WellsPlotProps) => {
  const t = useT();
  return (
    <svg
      className="wells-plot"
      viewBox={`${-PAD} ${-PAD} ${grid.ni + 2 * PAD} ${grid.nj + 2 * PAD}`}
      role="img"
      aria-label={t('map.ariaLabel')}
    >
      <rect
        x={0.5}
        y={0.5}
        width={grid.ni}
        height={grid.nj}
        fill="none"
        stroke={mapColors.frame}
        strokeWidth={0.3}
      />
      <text x={grid.ni + 1.5} y={0.5} fontSize={3.6} fill={mapColors.axisText} dominantBaseline="hanging">
        {`${t('map.axisI')} →`}
      </text>
      <text x={0.5} y={grid.nj + 4.5} fontSize={3.6} fill={mapColors.axisText}>
        {`${t('map.axisJ')} ↓`}
      </text>
      {wells.map((well) => {
        const active = filter === 'all' || well.layers.includes(filter);
        return (
          <circle
            key={well.id}
            cx={well.i}
            cy={well.j}
            r={active ? 1.1 : 0.7}
            fill={active ? wellColor(well.layers) : layerColors.dim}
            data-well-id={well.id}
            data-active={active}
            data-selected={well.id === selectedWell}
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
            <title>{`${well.id} (I=${well.i}, J=${well.j})`}</title>
          </circle>
        );
      })}
    </svg>
  );
};
