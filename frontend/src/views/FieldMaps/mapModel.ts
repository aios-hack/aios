import type { MapLayerFile, MapScale, MapsIndexFile, MapWell } from '../../api/types';

export const NODATA = 255;

export const QUANT_MAX = 254;

export interface CellHit {
  i: number;
  j: number;
  q: number;
  value: number | null;
}

export const decodeValue = (
  layer: MapLayerFile,
  q: number,
  scale: MapScale
): number | null => {
  if (q === layer.nodata) {
    return null;
  }
  if (scale === 'categorical') {
    return q;
  }
  const share = QUANT_MAX <= 0 ? 0 : q / QUANT_MAX;
  if (scale === 'log') {
    const low = Math.log10(Math.max(layer.min, 1e-9));
    const high = Math.log10(Math.max(layer.max, 1e-9));
    return 10 ** (low + share * (high - low));
  }
  return layer.min + share * (layer.max - layer.min);
};

export const cellAt = (
  layer: MapLayerFile,
  index: MapsIndexFile,
  scale: MapScale,
  i: number,
  j: number
): CellHit | null => {
  if (i < 0 || j < 0 || i >= index.ni || j >= index.nj) {
    return null;
  }
  const q = layer.q[j * index.ni + i];
  if (q === undefined) {
    return null;
  }
  return { i, j, q, value: decodeValue(layer, q, scale) };
};

export const categoryCount = (layer: MapLayerFile): number =>
  Math.max(Math.round(layer.max - layer.min) + 1, 1);

export const categoryIndex = (layer: MapLayerFile, q: number): number => {
  const base = Math.round(layer.min);
  const index = q - base;
  return index < 0 ? 0 : index;
};

export interface LayerPreset {
  id: string;
  kMin: number;
  kMax: number;
}

export const presetsOf = (index: MapsIndexFile): LayerPreset[] =>
  index.groups.map((group) => ({
    id: String(group.id),
    kMin: group.k_min,
    kMax: group.k_max
  }));

export const layerRange = (index: MapsIndexFile): { min: number; max: number } => {
  if (index.layers.length === 0) {
    return { min: 1, max: 1 };
  }
  let min = index.layers[0].k;
  let max = index.layers[0].k;
  for (const layer of index.layers) {
    if (layer.k < min) {
      min = layer.k;
    }
    if (layer.k > max) {
      max = layer.k;
    }
  }
  return { min, max };
};

export const wellsInLayer = (index: MapsIndexFile, k: number): MapWell[] =>
  index.wells.filter(
    (well) =>
      well.k_from === null ||
      well.k_to === null ||
      (k >= well.k_from && k <= well.k_to)
  );
