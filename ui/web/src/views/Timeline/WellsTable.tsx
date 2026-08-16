import type { TimelineWellRow } from '../../api/types';
import { useI18n } from '../../i18n/I18nContext';
import { DASH, formatNumber, formatPercent } from './format';

interface WellsTableProps {
  wells: TimelineWellRow[];
  selectedWell: string | null;
  onSelectWell: (well: string) => void;
}

const actualRate = (row: TimelineWellRow): number =>
  row.role === 'INJ' ? row.injection_rate : row.liquid_rate;

export const WellsTable = ({ wells, selectedWell, onSelectWell }: WellsTableProps) => {
  const { t, lang } = useI18n();
  const sorted = [...wells].sort((a, b) => a.well.localeCompare(b.well));

  return (
    <div className="timeline-table-wrap">
      <table className="timeline-table">
        <thead>
          <tr>
            <th scope="col">{t('steps.table.well')}</th>
            <th scope="col">{t('steps.table.availability')}</th>
            <th scope="col">{t('steps.table.role')}</th>
            <th scope="col">{t('steps.table.status')}</th>
            <th scope="col" className="timeline-cell-num">
              {t('steps.table.setpoint')}
            </th>
            <th scope="col" className="timeline-cell-num">
              {t('steps.table.actual')}
            </th>
            <th scope="col" className="timeline-cell-num">
              {t('steps.table.watercut')}
            </th>
            <th scope="col" className="timeline-cell-num">
              {t('steps.table.bhp')}
            </th>
          </tr>
        </thead>
        <tbody>
          {sorted.map((row) => {
            const notCommissioned = row.availability === 'NOT_COMMISSIONED';
            return (
              <tr
                key={row.well}
                data-well-id={row.well}
                data-not-commissioned={notCommissioned}
                data-selected={row.well === selectedWell}
                data-clickable="true"
                onClick={() => onSelectWell(row.well)}
              >
                <th scope="row">
                  <button type="button" className="timeline-well-button">
                    {row.well}
                  </button>
                </th>
                <td>{t(`steps.availability.${row.availability}`)}</td>
                <td>{notCommissioned ? DASH : t(`steps.role.${row.role}`)}</td>
                <td>
                  {notCommissioned ? DASH : t(`steps.status.${row.operating_status}`)}
                </td>
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
          })}
        </tbody>
      </table>
    </div>
  );
};
