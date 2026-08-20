export type SortDirection = 'asc' | 'desc';

interface SortHeaderProps {
  prefix: string;
  label: string;
  active: boolean;
  dir: SortDirection;
  title: string;
  numericClass?: string;
  onSort: () => void;
}

export const SortHeader = ({
  prefix,
  label,
  active,
  dir,
  title,
  numericClass,
  onSort
}: SortHeaderProps) => (
  <th
    scope="col"
    className={numericClass}
    aria-sort={active ? (dir === 'asc' ? 'ascending' : 'descending') : 'none'}
  >
    <button
      type="button"
      className={`${prefix}-sort-button`}
      data-active={active}
      title={title}
      onClick={onSort}
    >
      <span>{label}</span>
      <span className={`${prefix}-sort-arrow`} aria-hidden="true" data-active={active}>
        {active && dir === 'asc' ? '↑' : '↓'}
      </span>
    </button>
  </th>
);
