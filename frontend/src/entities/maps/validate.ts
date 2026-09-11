import type { MapLayerFile, MapsIndexFile } from '@/entities/maps/types';
import { isFilledArray, isNum, isNumArray, isNumOrNull, isRecord, isSafeArray, isStr } from '@/shared/api/guards';
import { isLayerRange } from '@/entities/wells/validate';

const MAP_SCALES = new Set(['linear', 'log', 'categorical']);

const isMapBounds = (data: unknown): boolean =>
  isRecord(data) &&
  isNum(data.xmin) &&
  isNum(data.xmax) &&
  isNum(data.ymin) &&
  isNum(data.ymax);

const isMapLayerRef = (data: unknown): boolean =>
  isRecord(data) && isNum(data.k) && (data.group === null || isNum(data.group));

const isMapPropRef = (data: unknown): boolean =>
  isRecord(data) && isStr(data.id) && isStr(data.scale) && MAP_SCALES.has(data.scale);

const isMapWell = (data: unknown): boolean =>
  isRecord(data) &&
  isStr(data.id) &&
  isNum(data.i) &&
  isNum(data.j) &&
  isNumOrNull(data.k_from) &&
  isNumOrNull(data.k_to) &&
  isNumArray(data.layers);

export const isMapsIndexFile = (data: unknown): data is MapsIndexFile =>
  isRecord(data) &&
  isNum(data.ni) &&
  isNum(data.nj) &&
  isNum(data.nk) &&
  isMapBounds(data.bounds) &&
  isSafeArray(data.groups) &&
  data.groups.every(isLayerRange) &&
  isFilledArray(data.layers) &&
  data.layers.every(isMapLayerRef) &&
  isFilledArray(data.props) &&
  data.props.every(isMapPropRef) &&
  isSafeArray(data.wells) &&
  data.wells.every(isMapWell) &&
  isStr(data.provenance);

export const isMapLayerFile = (data: unknown): data is MapLayerFile =>
  isRecord(data) &&
  isNum(data.k) &&
  isStr(data.prop) &&
  isNum(data.min) &&
  isNum(data.max) &&
  isNum(data.nodata) &&
  isNumArray(data.q);
