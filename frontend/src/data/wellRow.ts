import type { TimelineWellRow } from '../api/types';

export const actualRate = (row: TimelineWellRow): number =>
  row.role === 'INJ' ? row.injection_rate : row.liquid_rate;

export const isCommissioned = (row: TimelineWellRow): boolean =>
  row.availability !== 'NOT_COMMISSIONED';
