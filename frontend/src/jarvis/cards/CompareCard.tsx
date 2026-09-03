import { DASH, formatNumber } from '../../ui/format';
import { useI18n } from '../../i18n/I18nContext';
import { readCompare } from './cardPayloads';
import { EmptyPayload } from './EmptyPayload';
import './CompareCard.css';

export const CompareCard = ({ payload }: { payload: unknown }) => {
  const { lang, t } = useI18n();
  const compare = readCompare(payload);
  if (compare === null) {
    return <EmptyPayload />;
  }

  return (
    <div className="jarvis-compare">
      <div className="jarvis-compare-sides">
        {[compare.a, compare.b].map((side) => (
          <div className="jarvis-compare-side" key={side.id}>
            <p className="jarvis-compare-id">{side.id}</p>
            <p className="jarvis-compare-npv">
              {side.npv === null ? DASH : formatNumber(lang, side.npv)}
            </p>
            <p className="jarvis-compare-meta">
              <span>{side.status}</span>
              <span>
                {t('jarvis.compareConstraints')}: {side.constraints}
              </span>
            </p>
          </div>
        ))}
      </div>
      <p className="jarvis-compare-delta" data-sign={compare.delta_npv >= 0 ? 'up' : 'down'}>
        <span className="jarvis-compare-delta-label">{t('jarvis.compareDelta')}</span>
        {formatNumber(lang, compare.delta_npv)}
      </p>
      {compare.top_diff_wells.length === 0 ? null : (
        <div className="jarvis-compare-wells">
          <p className="jarvis-compare-wells-label">{t('jarvis.compareTopWells')}</p>
          <ol className="jarvis-compare-well-list">
            {compare.top_diff_wells.map((row) => (
              <li key={row.well} data-sign={row.delta >= 0 ? 'up' : 'down'}>
                <span className="jarvis-compare-well">{row.well}</span>
                <span className="jarvis-compare-well-delta">
                  {formatNumber(lang, row.delta)}
                </span>
              </li>
            ))}
          </ol>
        </div>
      )}
    </div>
  );
};
