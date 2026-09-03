import { DASH, formatNumber, formatPercent } from '../../ui/format';
import { useI18n } from '../../i18n/I18nContext';
import { readWellList } from './cardPayloads';
import { EmptyPayload } from './EmptyPayload';
import './WellListCard.css';

const barShare = (value: number, extreme: number): number =>
  extreme === 0 ? 0 : Math.min(1, Math.abs(value) / Math.abs(extreme));

export const WellListCard = ({ payload }: { payload: unknown }) => {
  const { lang, t } = useI18n();
  const listing = readWellList(payload);
  if (listing === null) {
    return <EmptyPayload />;
  }
  const extreme = listing.rows.reduce(
    (peak, row) => (Math.abs(row.value) > Math.abs(peak) ? row.value : peak),
    0
  );

  return (
    <ol className="jarvis-list">
      {listing.rows.map((row) => (
        <li className="jarvis-list-row" key={row.well} data-sign={row.value < 0 ? 'down' : 'up'}>
          <span className="jarvis-list-well">{row.well}</span>
          <span className="jarvis-list-bar" aria-hidden="true">
            <span
              className="jarvis-list-bar-fill"
              style={{ inlineSize: `${barShare(row.value, extreme) * 100}%` }}
            />
          </span>
          <span className="jarvis-list-value">{formatNumber(lang, row.value)}</span>
          <span className="jarvis-list-share">
            {row.share === null ? DASH : formatPercent(lang, row.share)}
          </span>
        </li>
      ))}
      <li className="jarvis-list-legend">
        <span>{listing.by}</span>
        <span>{listing.unit}</span>
        <span>{t('jarvis.listShare')}</span>
      </li>
    </ol>
  );
};
