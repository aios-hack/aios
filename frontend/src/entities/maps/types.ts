import type { LayerRange } from '@/entities/wells/types';

export type MapScale = 'linear' | 'log' | 'categorical';

export interface MapBounds {
  xmin: number;
  xmax: number;
  ymin: number;
  ymax: number;
}

export interface MapLayerRef {
  k: number;
  group: number | null;
}

export interface MapPropRef {
  id: string;
  scale: MapScale;
}

export interface MapWell {
  id: string;
  i: number;
  j: number;
  k_from: number | null;
  k_to: number | null;
  layers: number[];
}

export interface MapsIndexFile {
  ni: number;
  nj: number;
  nk: number;
  bounds: MapBounds;
  groups: LayerRange[];
  layers: MapLayerRef[];
  props: MapPropRef[];
  wells: MapWell[];
  provenance: string;
}

export interface MapLayerFile {
  k: number;
  prop: string;
  min: number;
  max: number;
  nodata: number;
  q: number[];
}
