import type { CSSProperties } from 'react';
import type { NpvFile } from '../../api/types';
import { useI18n } from '../../i18n/I18nContext';
import { formatNumber } from '../Timeline/format';
import { sortNpvRows, valueOf } from './sorting';
import type { NpvSortKey, SortDir, TaxMode } from './types';

interface NpvTableProps {
  data: NpvFile;
  mode: TaxMode;
  sortKey: NpvSortKey;
  dir: SortDir;
  onSort: (key: NpvSortKey) => void;
  selectedWell: string | null;
  onSelectWell: (well: string) => void;
}

export const NpvTable = ({
  data,
  mode,
  sortKey,
  dir,
  onSort,
  selectedWell,
  onSelectWell,
}: NpvTableProps) => {
  const { t, lang } = useI18n();
  const sorted = sortNpvRows(data.wells, sortKey, dir, mode);
  const maxAbs = data.wells.reduce(
    (best, row) => Math.max(best, Math.abs(valueOf(row, mode))),
    0,
  );
  const total = mode === 'preTax' ? data.total.pre_tax : data.total.with_allocated_tax;

  return (
    <div className="npv-table-block">
      <p className="npv-total">
        <span className="npv-total-label">{t('npv.table.total')}</span>
        <span className="npv-total-amount">
          <span
            className={total < 0 ? 'npv-total-value npv-danger' : 'npv-total-value'}
            data-testid="npv-total"
          >
            {formatNumber(lang, total)}
          </span>
          <span className="npv-total-unit">{t('npv.table.totalUnit')}</span>
        </span>
      </p>
      <div className="npv-table-wrap">
        <table className="npv-table">
          <thead>
            <tr>
              <th
                scope="col"
                aria-sort={
                  sortKey === 'well'
                    ? dir === 'asc'
                      ? 'ascending'
                      : 'descending'
                    : 'none'
                }
              >
                <button
                  type="button"
                  className="npv-sort-button"
                  data-active={sortKey === 'well'}
                  title={t(`npv.sort.${dir}`)}
                  onClick={() => onSort('well')}
                >
                  <span>{t('npv.table.well')}</span>
                  <span
                    className="npv-sort-arrow"
                    aria-hidden="true"
                    data-active={sortKey === 'well'}
                  >
                    {sortKey === 'well' && dir === 'asc' ? '↑' : '↓'}
                  </span>
                </button>
              </th>
              <th
                scope="col"
                className="npv-cell-num"
                aria-sort={
                  sortKey === 'value'
                    ? dir === 'asc'
                      ? 'ascending'
                      : 'descending'
                    : 'none'
                }
              >
                <button
                  type="button"
                  className="npv-sort-button"
                  data-active={sortKey === 'value'}
                  title={t(`npv.sort.${dir}`)}
                  onClick={() => onSort('value')}
                >
                  <span>{t(`npv.column.${mode}`)}</span>
                  <span
                    className="npv-sort-arrow"
                    aria-hidden="true"
                    data-active={sortKey === 'value'}
                  >
                    {sortKey === 'value' && dir === 'asc' ? '↑' : '↓'}
                  </span>
                </button>
              </th>
              <th scope="col" className="npv-cell-bar">
                {t('npv.table.bar')}
              </th>
            </tr>
          </thead>
          <tbody>
            {sorted.map((row) => {
              const value = valueOf(row, mode);
              const negative = value < 0;
              const ratio = maxAbs > 0 ? Math.abs(value) / maxAbs : 0;
              return (
                <tr
                  key={row.well}
                  data-well-id={row.well}
                  data-selected={row.well === selectedWell}
                  data-clickable="true"
                  onClick={() => onSelectWell(row.well)}
                >
                  <th scope="row">
                    <button type="button" className="npv-well-button">
                      {row.well}
                    </button>
                  </th>
                  <td className={negative ? 'npv-cell-num npv-danger' : 'npv-cell-num'}>
                    {formatNumber(lang, value)}
                  </td>
                  <td className="npv-cell-bar">
                    <div className="npv-bar-track">
                      <div
                        className={negative ? 'npv-bar npv-bar-danger' : 'npv-bar'}
                        style={{ '--npv-bar-ratio': `${ratio * 100}%` } as CSSProperties}
                      />
                    </div>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
};
