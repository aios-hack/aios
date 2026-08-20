import type { NpvWellRow } from '../../api/types';
import { compareWellIds } from '../../ui/format';
import type { NpvSortKey, SortDir, TaxMode } from './types';

export const valueOf = (row: NpvWellRow, mode: TaxMode): number =>
  mode === 'preTax' ? row.pre_tax : row.with_allocated_tax;

const compareWell = (a: NpvWellRow, b: NpvWellRow): number =>
  compareWellIds(a.well, b.well);

export const sortNpvRows = (
  rows: readonly NpvWellRow[],
  key: NpvSortKey,
  dir: SortDir,
  mode: TaxMode
): NpvWellRow[] => {
  const sorted = [...rows];
  sorted.sort((a, b) => {
    if (key === 'well') {
      const diff = compareWell(a, b);
      return dir === 'asc' ? diff : -diff;
    }
    const diff = valueOf(a, mode) - valueOf(b, mode);
    if (diff === 0) {
      return compareWell(a, b);
    }
    return dir === 'asc' ? diff : -diff;
  });
  return sorted;
};
