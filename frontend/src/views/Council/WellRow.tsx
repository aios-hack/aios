import { memo, useCallback, type CSSProperties } from 'react';
import type { Lang } from '../../i18n/dictionaries';
import { DASH, formatNumber } from '../../ui/format';
import { dimState, type CouncilPath, type WellRow as WellRowData } from './levels';
import { decisionAmount, decisionVerb } from './wellSorting';

interface WellRowProps {
  row: WellRowData;
  index: number;
  path: CouncilPath | null;
  lang: Lang;
  t: (key: string, vars?: Record<string, string | number>) => string;
  onSelectWell: (well: string) => void;
}

const numericCell = (lang: Lang, value: number | null) =>
  value === null ? (
    <span className="council-muted">{DASH}</span>
  ) : (
    formatNumber(lang, value, 1)
  );

const WellRowView = ({ row, index, path, lang, t, onSelectWell }: WellRowProps) => {
  const selected = path?.well === row.well;
  const select = useCallback(() => onSelectWell(row.well), [onSelectWell, row.well]);
  const selectOnly = useCallback(
    (event: { stopPropagation: () => void }) => {
      event.stopPropagation();
      onSelectWell(row.well);
    },
    [onSelectWell, row.well]
  );

  return (
    <tr
      data-testid={`council-well-${row.well}`}
      data-state={dimState(path, selected)}
      data-selected={selected}
      style={{ '--council-row-index': index } as CSSProperties}
      onClick={select}
    >
      <th scope="row">
        <button
          type="button"
          className="council-well-button"
          aria-label={t('council.wells.open', { well: row.well })}
          onClick={selectOnly}
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
      <td className="council-cell-num">{numericCell(lang, decisionAmount(row.decision))}</td>
      <td>
        <span className="council-rule" title={t(`council.rule.${row.rule}`)}>
          {row.rule}
        </span>
      </td>
      <td className="council-cell-num">
        {numericCell(lang, row.inputs.group_limit_m3_per_day ?? null)}
      </td>
      <td className="council-cell-num">
        {numericCell(lang, row.inputs.injection_rate_m3_per_day ?? null)}
      </td>
      <td className="council-cell-num">
        {numericCell(lang, row.inputs.liquid_rate_m3_per_day ?? null)}
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
  );
};

export const WellRow = memo(WellRowView);
