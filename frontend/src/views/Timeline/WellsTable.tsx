import { memo, useCallback, useMemo, useState } from 'react';
import type { TimelineWellRow } from '../../api/types';
import { useI18n } from '../../i18n/I18nContext';
import { SortableHeader } from './SortableHeader';
import { isNumericKey, SORT_KEYS, sortWells, type SortDir, type SortKey } from './sorting';
import { WellRow } from './WellRow';
import './WellsTable.css';

interface WellsTableProps {
  wells: TimelineWellRow[];
  selectedWell: string | null;
  onSelectWell: (well: string) => void;
}

const WellsTableView = ({ wells, selectedWell, onSelectWell }: WellsTableProps) => {
  const { t, lang } = useI18n();
  const [sortKey, setSortKey] = useState<SortKey>('well');
  const [dir, setDir] = useState<SortDir>('asc');

  const onSort = useCallback(
    (key: SortKey) => {
      if (key === sortKey) {
        setDir((current) => (current === 'asc' ? 'desc' : 'asc'));
        return;
      }
      setSortKey(key);
      setDir(isNumericKey(key) ? 'desc' : 'asc');
    },
    [sortKey]
  );

  const sorted = useMemo(() => sortWells(wells, sortKey, dir), [wells, sortKey, dir]);

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
          {sorted.map((row) => (
            <WellRow
              key={row.well}
              row={row}
              selected={row.well === selectedWell}
              lang={lang}
              t={t}
              onSelectWell={onSelectWell}
            />
          ))}
        </tbody>
      </table>
    </div>
  );
};

export const WellsTable = memo(WellsTableView);
