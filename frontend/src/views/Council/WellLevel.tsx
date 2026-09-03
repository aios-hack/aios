import { useCallback, useMemo, useState } from 'react';
import { useI18n } from '../../i18n/I18nContext';
import type { CouncilPath, WellRow as WellRowData } from './levels';
import { WellRow } from './WellRow';
import { WellSortHeader } from './WellSortHeader';
import {
  isNumericWellKey,
  sortWellRows,
  WELL_SORT_KEYS,
  type SortDir,
  type WellSortKey
} from './wellSorting';

interface WellLevelProps {
  rows: readonly WellRowData[];
  groupLabel: string | null;
  path: CouncilPath | null;
  onSelectWell: (well: string) => void;
}

const COLUMN_LABEL: Record<WellSortKey, string> = {
  well: 'council.wells.well',
  decision: 'council.wells.decision',
  amount: 'council.wells.amount',
  rule: 'council.wells.rule',
  groupLimit: 'council.input.group_limit_m3_per_day',
  injection: 'council.input.injection_rate_m3_per_day',
  liquid: 'council.input.liquid_rate_m3_per_day',
  constraint: 'council.wells.constraint'
};

export const WellLevel = ({ rows, groupLabel, path, onSelectWell }: WellLevelProps) => {
  const { t, lang } = useI18n();
  const [sort, setSort] = useState<{ key: WellSortKey; dir: SortDir }>({
    key: 'well',
    dir: 'asc'
  });
  const { key: sortKey, dir } = sort;

  const sorted = useMemo(() => sortWellRows(rows, sortKey, dir), [rows, sortKey, dir]);

  const onSort = useCallback((key: WellSortKey) => {
    setSort((current) =>
      current.key === key
        ? { key, dir: current.dir === 'asc' ? 'desc' : 'asc' }
        : { key, dir: 'asc' }
    );
  }, []);

  const title =
    groupLabel === null
      ? t('council.wells.titleUngrouped')
      : t('council.wells.title', { group: groupLabel });

  return (
    <section
      className="council-level"
      data-level="wells"
      data-testid="council-wells"
      data-guide="council-wells"
    >
      <h3 className="council-level-title">{title}</h3>
      {sorted.length === 0 ? (
        <p className="inline-empty">{t('council.wells.empty')}</p>
      ) : (
        <div className="council-table-wrap">
          <table className="council-table">
            <caption className="visually-hidden">{title}</caption>
            <colgroup>
              <col className="council-col-well" />
              <col className="council-col-decision" />
              <col className="council-col-num" />
              <col className="council-col-rule" />
              <col className="council-col-num" />
              <col className="council-col-num" />
              <col className="council-col-num" />
              <col className="council-col-constraint" />
            </colgroup>
            <thead>
              <tr>
                {WELL_SORT_KEYS.map((key) => (
                  <WellSortHeader
                    key={key}
                    columnKey={key}
                    label={t(COLUMN_LABEL[key])}
                    numeric={isNumericWellKey(key)}
                    activeKey={sortKey}
                    dir={dir}
                    onSort={onSort}
                  />
                ))}
              </tr>
            </thead>
            <tbody>
              {sorted.map((row, index) => (
                <WellRow
                  key={row.well}
                  row={row}
                  index={index}
                  path={path}
                  lang={lang}
                  t={t}
                  onSelectWell={onSelectWell}
                />
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
};
