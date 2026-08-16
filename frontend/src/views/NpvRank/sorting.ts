import type { NpvWellRow } from '../../api/types';
import type { NpvSortKey, SortDir, TaxMode } from './types';

export const valueOf = (row: NpvWellRow, mode: TaxMode): number =>
  mode === 'preTax' ? row.pre_tax : row.with_allocated_tax;

const wellOrder = (well: string): [number, string] => {
  const numeric = Number(well);
  return Number.isFinite(numeric) ? [numeric, ''] : [Number.POSITIVE_INFINITY, well];
};

const compareWell = (a: NpvWellRow, b: NpvWellRow): number => {
  const [numA, textA] = wellOrder(a.well);
  const [numB, textB] = wellOrder(b.well);
  return numA === numB ? textA.localeCompare(textB) : numA - numB;
};

export const sortNpvRows = (
  rows: readonly NpvWellRow[],
  key: NpvSortKey,
  dir: SortDir,
  mode: TaxMode
): NpvWellRow[] => {
  const sorted = [...rows];
  sorted.sort((a, b) => {
    const diff =
      key === 'well' ? compareWell(a, b) : valueOf(a, mode) - valueOf(b, mode);
    const resolved = diff === 0 && key !== 'well' ? compareWell(a, b) : diff;
    return dir === 'asc' ? resolved : -resolved;
  });
  return sorted;
};
