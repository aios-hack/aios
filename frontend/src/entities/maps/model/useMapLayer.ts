import type { MapLayerFile } from '@/entities/maps/types';
import type { ResourceState } from '@/shared/api/ResourceState';
import { useJsonResource } from '@/shared/api/useJsonResource';
import { isMapLayerFile } from '@/entities/maps/validate';

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
