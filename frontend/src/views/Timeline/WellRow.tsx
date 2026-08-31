import { memo, type CSSProperties } from 'react';
import type { TimelineWellRow } from '../../api/types';
import { actualRate } from '../../data';
import type { Lang, Translate } from '../../i18n/I18nContext';
import { DASH, formatNumber, formatPercent } from '../../ui/format';

interface WellRowProps {
  row: TimelineWellRow;
  selected: boolean;
  ordinal: number;
  lang: Lang;
  t: Translate;
  onSelectWell: (well: string) => void;
}

const WellRowView = ({ row, selected, ordinal, lang, t, onSelectWell }: WellRowProps) => {
  const notCommissioned = row.availability === 'NOT_COMMISSIONED';

  return (
    <tr
      data-well-id={row.well}
      data-not-commissioned={notCommissioned}
      data-selected={selected}
      data-clickable="true"
      data-ordinal={ordinal}
      style={{ '--timeline-row-index': ordinal } as CSSProperties}
      onClick={() => onSelectWell(row.well)}
    >
      <th scope="row">
        <button
          type="button"
          className="timeline-well-button"
          aria-label={t('steps.table.openWell', { well: row.well })}
          onClick={(event) => {
            event.stopPropagation();
            onSelectWell(row.well);
          }}
        >
          {row.well}
        </button>
      </th>
      <td>{t(`steps.availability.${row.availability}`)}</td>
      <td>{notCommissioned ? DASH : t(`steps.role.${row.role}`)}</td>
      <td>{notCommissioned ? DASH : t(`steps.status.${row.operating_status}`)}</td>
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
};

export const WellRow = memo(WellRowView);
