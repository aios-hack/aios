import type { NpvFile, NpvWellRow } from '../../api/types';
import { useI18n } from '../../i18n/I18nContext';
import { formatNumber } from '../Timeline/format';
import type { SortDir, TaxMode } from './types';

interface NpvTableProps {
  data: NpvFile;
  mode: TaxMode;
  dir: SortDir;
  onToggleDir: () => void;
  selectedWell: string | null;
  onSelectWell: (well: string) => void;
}

const valueOf = (row: NpvWellRow, mode: TaxMode): number =>
  mode === 'preTax' ? row.pre_tax : row.with_allocated_tax;

export const NpvTable = ({
  data,
  mode,
  dir,
  onToggleDir,
  selectedWell,
  onSelectWell
}: NpvTableProps) => {
  const { t, lang } = useI18n();
  const sorted = [...data.wells].sort((a, b) =>
    dir === 'desc' ? valueOf(b, mode) - valueOf(a, mode) : valueOf(a, mode) - valueOf(b, mode)
  );
  const maxAbs = data.wells.reduce(
    (best, row) => Math.max(best, Math.abs(valueOf(row, mode))),
    0
  );
  const total = mode === 'preTax' ? data.total.pre_tax : data.total.with_allocated_tax;

  return (
    <div className="npv-table-wrap">
      <table className="npv-table">
        <thead>
          <tr>
            <th scope="col">{t('npv.table.well')}</th>
            <th
              scope="col"
              className="npv-cell-num"
              aria-sort={dir === 'desc' ? 'descending' : 'ascending'}
            >
              <button
                type="button"
                className="npv-sort-button"
                title={t(`npv.sort.${dir}`)}
                onClick={onToggleDir}
              >
                <span>{t(`npv.column.${mode}`)}</span>
                <span className="npv-sort-arrow" aria-hidden="true">
                  {dir === 'desc' ? '↓' : '↑'}
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
                      style={{ transform: `scaleX(${ratio})` }}
                    />
                  </div>
                </td>
              </tr>
            );
          })}
        </tbody>
        <tfoot>
          <tr className="npv-total-row">
            <th scope="row">{t('npv.table.total')}</th>
            <td className={total < 0 ? 'npv-cell-num npv-danger' : 'npv-cell-num'}>
              {formatNumber(lang, total)}
            </td>
            <td className="npv-cell-bar" />
          </tr>
        </tfoot>
      </table>
    </div>
  );
};
