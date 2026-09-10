import type { MapLayerFile } from '../api/types';
import type { ResourceState } from './ResourceState';
import { useJsonResource } from './useJsonResource';
import { isMapLayerFile } from './validators';

export const mapLayerUrl = (prop: string, k: number): string =>
  `/data/maps/${prop}/${k}.json`;

export const useMapLayer = (
  prop: string | null,
  k: number | null
): ResourceState<MapLayerFile> =>
  useJsonResource(
    prop === null || k === null ? null : mapLayerUrl(prop, k),
    isMapLayerFile
  );
