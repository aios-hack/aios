import { memo, type CSSProperties } from 'react';
import type { Lang, Translate } from '../../i18n/I18nContext';
import { formatNumber } from '../../ui/format';

interface NpvRowProps {
  well: string;
  value: number;
  ratio: number;
  selected: boolean;
  lang: Lang;
  t: Translate;
  onSelectWell: (well: string) => void;
}

const NpvRowView = ({
  well,
  value,
  ratio,
  selected,
  lang,
  t,
  onSelectWell
}: NpvRowProps) => {
  const negative = value < 0;

  return (
    <tr
      data-well-id={well}
      data-selected={selected}
      data-clickable="true"
      onClick={() => onSelectWell(well)}
    >
      <th scope="row">
        <button
          type="button"
          className="npv-well-button"
          aria-label={t('npv.table.openWell', { well })}
          onClick={(event) => {
            event.stopPropagation();
            onSelectWell(well);
          }}
        >
          {well}
        </button>
      </th>
      <td className={negative ? 'npv-cell-num npv-danger' : 'npv-cell-num'}>
        {formatNumber(lang, value)}
      </td>
      <td className="npv-cell-bar">
        <div className="npv-bar-track">
          <div
            className={negative ? 'npv-bar npv-bar-danger' : 'npv-bar'}
            style={
              {
                '--npv-bar-ratio': Math.min(Math.max(ratio, 0.006), 1)
              } as CSSProperties
            }
          />
        </div>
      </td>
    </tr>
  );
};

export const NpvRow = memo(NpvRowView);
