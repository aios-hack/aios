import { useT } from '../../i18n/I18nContext';
import { SortHeader } from '../../ui/SortHeader';
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
    <SortHeader
      prefix="timeline"
      label={label}
      active={active}
      dir={dir}
      title={t(active && dir === 'asc' ? 'steps.sort.asc' : 'steps.sort.desc')}
      numericClass={numeric ? 'timeline-cell-num' : undefined}
      onSort={() => onSort(columnKey)}
    />
  );
};
