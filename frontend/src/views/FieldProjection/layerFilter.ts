import type { LayerRange, WellPoint, WellsFile } from '../../api/types';

export type LayerFilter = 'all' | number;

export interface LayerOption {
  value: LayerFilter;
  id: number | null;
}

export const layerOptions = (layers: LayerRange[]): LayerOption[] => [
  { value: 'all', id: null },
  ...layers.map((layer) => ({ value: layer.id, id: layer.id }))
];

export const isWellDimmed = (well: WellPoint, filter: LayerFilter): boolean =>
  filter !== 'all' && !well.layers.includes(filter);

export const shownCount = (wells: WellsFile, filter: LayerFilter): number =>
  filter === 'all'
    ? wells.wells.length
    : wells.wells.filter((well) => well.layers.includes(filter)).length;

export const dimmedWellIds = (wells: WellsFile, filter: LayerFilter): Set<string> =>
  new Set(
    wells.wells.filter((well) => isWellDimmed(well, filter)).map((well) => well.id)
  );
