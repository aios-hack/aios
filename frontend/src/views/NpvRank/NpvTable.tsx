import { memo, useMemo } from 'react';
import type { NpvFile } from '../../api/types';
import { useI18n } from '../../i18n/I18nContext';
import { formatNumber } from '../../ui/format';
import { SortHeader } from '../../ui/SortHeader';
import { NpvRow } from './NpvRow';
import { sortNpvRows, valueOf } from './sorting';
import type { NpvSortKey, SortDir, TaxMode } from './types';

const STAGGER_ROW_CAP = 12;

interface NpvTableProps {
  data: NpvFile;
  mode: TaxMode;
  sortKey: NpvSortKey;
  dir: SortDir;
  onSort: (key: NpvSortKey) => void;
  selectedWell: string | null;
  onSelectWell: (well: string) => void;
}

const NpvTableView = ({
  data,
  mode,
  sortKey,
  dir,
  onSort,
  selectedWell,
  onSelectWell,
}: NpvTableProps) => {
  const { t, lang } = useI18n();
  const sorted = useMemo(
    () => sortNpvRows(data.wells, sortKey, dir, mode),
    [data.wells, sortKey, dir, mode],
  );
  const maxAbs = useMemo(
    () =>
      data.wells.reduce((best, row) => Math.max(best, Math.abs(valueOf(row, mode))), 0),
    [data.wells, mode],
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
      <div className="npv-table-wrap" data-guide="npv-rank-table">
        <table className="npv-table">
          <caption className="visually-hidden">{t('npv.table.caption')}</caption>
          <thead>
            <tr>
              <SortHeader
                prefix="npv"
                label={t('npv.table.well')}
                active={sortKey === 'well'}
                dir={dir}
                title={t('npv.sort.action')}
                onSort={() => onSort('well')}
              />
              <SortHeader
                prefix="npv"
                label={t(`npv.column.${mode}`)}
                active={sortKey === 'value'}
                dir={dir}
                title={t('npv.sort.action')}
                numericClass="npv-cell-num"
                onSort={() => onSort('value')}
              />
              <th scope="col" className="npv-cell-bar">
                {t('npv.table.bar')}
              </th>
            </tr>
          </thead>
          <tbody>
            {sorted.map((row, index) => {
              const value = valueOf(row, mode);
              return (
                <NpvRow
                  key={row.well}
                  well={row.well}
                  value={value}
                  index={Math.min(index, STAGGER_ROW_CAP)}
                  ratio={maxAbs > 0 ? Math.abs(value) / maxAbs : 0}
                  selected={row.well === selectedWell}
                  lang={lang}
                  t={t}
                  onSelectWell={onSelectWell}
                />
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
};

export const NpvTable = memo(NpvTableView);
