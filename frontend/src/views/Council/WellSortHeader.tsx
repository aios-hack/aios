import { useI18n } from '../../i18n/I18nContext';
import type { SortDir, WellSortKey } from './wellSorting';

interface WellSortHeaderProps {
  columnKey: WellSortKey;
  label: string;
  numeric: boolean;
  activeKey: WellSortKey;
  dir: SortDir;
  onSort: (key: WellSortKey) => void;
}

export const WellSortHeader = ({
  columnKey,
  label,
  numeric,
  activeKey,
  dir,
  onSort
}: WellSortHeaderProps) => {
  const { t } = useI18n();
  const active = activeKey === columnKey;

  return (
    <th
      scope="col"
      className={numeric ? 'council-cell-num' : undefined}
      aria-sort={active ? (dir === 'asc' ? 'ascending' : 'descending') : 'none'}
    >
      <button
        type="button"
        className="council-sort-button"
        data-active={active}
        title={t(active && dir === 'asc' ? 'council.sort.asc' : 'council.sort.desc')}
        onClick={() => onSort(columnKey)}
      >
        <span className="council-sort-label">{label}</span>
        <span className="council-sort-arrow" aria-hidden="true" data-active={active}>
          {active && dir === 'asc' ? '↑' : '↓'}
        </span>
      </button>
    </th>
  );
};
