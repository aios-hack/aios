import { DASH, formatNumber } from '../../ui/format';
import { useI18n } from '../../i18n/I18nContext';
import { readRunList } from './cardPayloads';
import { EmptyPayload } from './EmptyPayload';
import './RunListCard.css';

export const RunListCard = ({ payload }: { payload: unknown }) => {
  const { lang, t } = useI18n();
  const list = readRunList(payload);
  if (list === null) {
    return <EmptyPayload />;
  }

  return (
    <div className="jarvis-runs">
      <table className="jarvis-runs-table">
        <thead>
          <tr>
            <th scope="col">{t('jarvis.runId')}</th>
            <th scope="col">{t('jarvis.runStatus')}</th>
            <th scope="col">{t('jarvis.runNpv')}</th>
          </tr>
        </thead>
        <tbody>
          {list.rows.map((row) => (
            <tr key={row.run_id} data-sound={row.sound === true ? 'true' : undefined}>
              <th scope="row">
                <span className="jarvis-runs-id">{row.run_id}</span>
                {row.strategy === null ? null : (
                  <span className="jarvis-runs-strategy">{row.strategy}</span>
                )}
              </th>
              <td>{row.status ?? DASH}</td>
              <td className="jarvis-runs-npv">
                {row.verified_npv === null
                  ? row.predicted_npv === null
                    ? DASH
                    : formatNumber(lang, row.predicted_npv)
                  : formatNumber(lang, row.verified_npv)}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      <p className="jarvis-runs-total">{t('jarvis.runTotal', { count: String(list.total) })}</p>
    </div>
  );
};
