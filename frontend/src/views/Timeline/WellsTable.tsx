import { useState } from 'react';
import type { TimelineWellRow } from '../../api/types';
import { useI18n } from '../../i18n/I18nContext';
import { DASH, formatNumber, formatPercent } from './format';
import { SortableHeader } from './SortableHeader';
import { actualRate, isNumericKey, SORT_KEYS, sortWells, type SortDir, type SortKey } from './sorting';

interface WellsTableProps {
  wells: TimelineWellRow[];
  selectedWell: string | null;
  onSelectWell: (well: string) => void;
}

export const WellsTable = ({ wells, selectedWell, onSelectWell }: WellsTableProps) => {
  const { t, lang } = useI18n();
  const [sortKey, setSortKey] = useState<SortKey>('well');
  const [dir, setDir] = useState<SortDir>('asc');

  const onSort = (key: SortKey) => {
    if (key === sortKey) {
      setDir((current) => (current === 'asc' ? 'desc' : 'asc'));
      return;
    }
    setSortKey(key);
    setDir(isNumericKey(key) ? 'desc' : 'asc');
  };

  const sorted = sortWells(wells, sortKey, dir);

  return (
    <div className="timeline-table-wrap">
      <table className="timeline-table">
        <thead>
          <tr>
            {SORT_KEYS.map((key) => (
              <SortableHeader
                key={key}
                columnKey={key}
                label={t(`steps.table.${key}`)}
                numeric={isNumericKey(key)}
                activeKey={sortKey}
                dir={dir}
                onSort={onSort}
              />
            ))}
          </tr>
        </thead>
        <tbody>
          {sorted.map((row) => {
            const notCommissioned = row.availability === 'NOT_COMMISSIONED';
            return (
              <tr
                key={row.well}
                data-well-id={row.well}
                data-not-commissioned={notCommissioned}
                data-selected={row.well === selectedWell}
                data-clickable="true"
                onClick={() => onSelectWell(row.well)}
              >
                <th scope="row">
                  <button type="button" className="timeline-well-button">
                    {row.well}
                  </button>
                </th>
                <td>{t(`steps.availability.${row.availability}`)}</td>
                <td>{notCommissioned ? DASH : t(`steps.role.${row.role}`)}</td>
                <td>
                  {notCommissioned ? DASH : t(`steps.status.${row.operating_status}`)}
                </td>
                <td className="timeline-cell-num">
                  {notCommissioned ? DASH : formatNumber(lang, row.setpoint, 1)}
                </td>
                <td className="timeline-cell-num">
                  {notCommissioned ? DASH : formatNumber(lang, actualRate(row), 1)}
                </td>
                <td className="timeline-cell-num">
                  {notCommissioned || row.watercut === null
                    ? DASH
                    : formatPercent(lang, row.watercut)}
                </td>
                <td className="timeline-cell-num">
                  {notCommissioned ? DASH : formatNumber(lang, row.bhp, 1)}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
};
