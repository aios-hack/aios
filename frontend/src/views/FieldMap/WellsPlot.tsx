import { useMemo } from 'react';
import type { GridSize, WellPoint } from '../../api/types';
import { useT } from '../../i18n/I18nContext';
import type { LayerFilter } from './LayerSwitch';
import { PlotAxes } from './PlotAxes';
import type { WellRole } from './roles';
import { WellMarker } from './WellMarker';

export { wellColor } from './WellMarker';

const PAD_LEFT = 16;
const PAD_TOP = 12;
const PAD_RIGHT = 12;
const PAD_BOTTOM = 11;
const MARGIN = 3;
const TICK_ROUND = 5;

const extentOf = (wells: WellPoint[], grid: GridSize): { ni: number; nj: number } => {
  if (wells.length === 0) {
    return { ni: grid.ni, nj: grid.nj };
  }
  let maxI = wells[0].i;
  let maxJ = wells[0].j;
  for (const well of wells) {
    if (well.i > maxI) {
      maxI = well.i;
    }
    if (well.j > maxJ) {
      maxJ = well.j;
    }
  }
  return {
    ni: Math.min(grid.ni, Math.ceil((maxI + MARGIN) / TICK_ROUND) * TICK_ROUND),
    nj: Math.min(grid.nj, Math.ceil((maxJ + MARGIN) / TICK_ROUND) * TICK_ROUND)
  };
};

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
  const extent = useMemo(() => extentOf(wells, grid), [wells, grid]);

  return (
    <svg
      className="wells-plot"
      viewBox={`${-PAD_LEFT} ${-PAD_TOP} ${extent.ni + PAD_LEFT + PAD_RIGHT} ${extent.nj + PAD_TOP + PAD_BOTTOM}`}
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
      <rect x={0} y={0} width={extent.ni} height={extent.nj} fill="url(#map-grid)" />
      <PlotAxes grid={extent} axisI={t('map.axisI')} axisJ={t('map.axisJ')} />
      {wells.map((well) => (
        <WellMarker
          key={well.id}
          well={well}
          active={filter === 'all' || well.layers.includes(filter)}
          selected={well.id === selectedWell}
          role={roles.get(well.id) ?? null}
          onSelectWell={onSelectWell}
        />
      ))}
    </svg>
  );
};
