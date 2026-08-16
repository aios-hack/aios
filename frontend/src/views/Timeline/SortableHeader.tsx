import { useT } from '../../i18n/I18nContext';
import type { SortDir, SortKey } from './sorting';

interface SortableHeaderProps {
  columnKey: SortKey;
  label: string;
  numeric: boolean;
  activeKey: SortKey;
  dir: SortDir;
  onSort: (key: SortKey) => void;
}

export const SortableHeader = ({
  columnKey,
  label,
  numeric,
  activeKey,
  dir,
  onSort
}: SortableHeaderProps) => {
  const t = useT();
  const active = activeKey === columnKey;

  return (
    <th
      scope="col"
      className={numeric ? 'timeline-cell-num' : undefined}
      aria-sort={active ? (dir === 'asc' ? 'ascending' : 'descending') : 'none'}
    >
      <button
        type="button"
        className="timeline-sort-button"
        data-active={active}
        title={t(active && dir === 'asc' ? 'steps.sort.asc' : 'steps.sort.desc')}
        onClick={() => onSort(columnKey)}
      >
        <span>{label}</span>
        <span className="timeline-sort-arrow" aria-hidden="true" data-active={active}>
          {active && dir === 'asc' ? '↑' : '↓'}
        </span>
      </button>
    </th>
  );
};
