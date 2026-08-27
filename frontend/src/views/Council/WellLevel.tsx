import { useMemo, useState } from 'react';
import { useI18n } from '../../i18n/I18nContext';
import { DASH, formatNumber } from '../../ui/format';
import { dimState, type CouncilPath, type WellRow } from './levels';
import { WellSortHeader } from './WellSortHeader';
import {
  decisionAmount,
  decisionVerb,
  isNumericWellKey,
  sortWellRows,
  WELL_SORT_KEYS,
  type SortDir,
  type WellSortKey
} from './wellSorting';

interface WellLevelProps {
  rows: readonly WellRow[];
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

const Numeric = ({ value }: { value: number | null }) => {
  const { lang } = useI18n();
  if (value === null) {
    return <span className="council-muted">{DASH}</span>;
  }
  return <>{formatNumber(lang, value, 1)}</>;
};

export const WellLevel = ({ rows, groupLabel, path, onSelectWell }: WellLevelProps) => {
  const { t } = useI18n();
  const [sortKey, setSortKey] = useState<WellSortKey>('well');
  const [dir, setDir] = useState<SortDir>('asc');

  const sorted = useMemo(() => sortWellRows(rows, sortKey, dir), [rows, sortKey, dir]);

  const onSort = (key: WellSortKey) => {
    if (key === sortKey) {
      setDir((current) => (current === 'asc' ? 'desc' : 'asc'));
      return;
    }
    setSortKey(key);
    setDir('asc');
  };

  const title =
    groupLabel === null
      ? t('council.wells.titleUngrouped')
      : t('council.wells.title', { group: groupLabel });

  return (
    <section className="council-level" data-level="wells" data-testid="council-wells">
      <h3 className="council-level-title">{title}</h3>
      {sorted.length === 0 ? (
        <p className="council-empty">{t('council.wells.empty')}</p>
      ) : (
        <div className="council-table-wrap">
          <table className="council-table">
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
              {sorted.map((row) => (
                <tr
                  key={row.well}
                  data-testid={`council-well-${row.well}`}
                  data-state={dimState(path, path?.well === row.well)}
                  data-selected={path?.well === row.well}
                  onClick={() => onSelectWell(row.well)}
                >
                  <th scope="row">
                    <button
                      type="button"
                      className="council-well-button"
                      aria-label={t('council.wells.open', { well: row.well })}
                      onClick={(event) => {
                        event.stopPropagation();
                        onSelectWell(row.well);
                      }}
                    >
                      {row.color !== null && (
                        <span className="council-swatch" style={{ background: row.color }} />
                      )}
                      <span className="council-number">{row.well}</span>
                    </button>
                  </th>
                  <td>
                    <span className="council-verb">{decisionVerb(row.decision)}</span>
                  </td>
                  <td className="council-cell-num">
                    <Numeric value={decisionAmount(row.decision)} />
                  </td>
                  <td>
                    <span className="council-rule" title={t(`council.rule.${row.rule}`)}>
                      {row.rule}
                    </span>
                  </td>
                  <td className="council-cell-num">
                    <Numeric value={row.inputs.group_limit_m3_per_day ?? null} />
                  </td>
                  <td className="council-cell-num">
                    <Numeric value={row.inputs.injection_rate_m3_per_day ?? null} />
                  </td>
                  <td className="council-cell-num">
                    <Numeric value={row.inputs.liquid_rate_m3_per_day ?? null} />
                  </td>
                  <td>
                    {row.constraint === null ? (
                      <span className="council-muted">{t('council.wells.noConstraint')}</span>
                    ) : (
                      <span
                        className="council-constraint"
                        data-testid={`council-constraint-${row.well}`}
                      >
                        {t(`council.constraint.${row.constraint}`)}
                      </span>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
};
