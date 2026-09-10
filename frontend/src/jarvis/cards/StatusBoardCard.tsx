import { DASH, formatNumber } from '../../ui/format';
import { useI18n } from '../../i18n/I18nContext';
import { readStatusBoard } from './cardPayloads';
import { EmptyPayload } from './EmptyPayload';
import './StatusBoardCard.css';

export const StatusBoardCard = ({ payload }: { payload: unknown }) => {
  const { lang, t } = useI18n();
  const board = readStatusBoard(payload);
  if (board === null) {
    return <EmptyPayload />;
  }
  const { champion, last_run: last } = board;

  return (
    <div className="jarvis-board">
      <section className="jarvis-board-block">
        <p className="jarvis-board-label">{t('jarvis.boardChampion')}</p>
        {champion.recorded ? (
          <>
            <p className="jarvis-board-value">
              {champion.npv === null ? DASH : formatNumber(lang, champion.npv)}
            </p>
            <p className="jarvis-board-flags">
              <span data-on={champion.sound === true ? 'true' : 'false'}>
                {t('jarvis.compareSound')}
              </span>
              {champion.ood === null ? null : (
                <span data-on="true">
                  {t('jarvis.compareOod')} {formatNumber(lang, champion.ood, 2)}
                </span>
              )}
            </p>
          </>
        ) : (
          <p className="jarvis-board-missing">{champion.reason ?? t('jarvis.boardNoRun')}</p>
        )}
      </section>
      <section className="jarvis-board-block">
        <p className="jarvis-board-label">{t('jarvis.boardLastRun')}</p>
        {last.recorded ? (
          <>
            <p className="jarvis-board-run">{last.run_id ?? DASH}</p>
            <p className="jarvis-board-value">
              {last.verified_npv === null
                ? last.predicted_npv === null
                  ? DASH
                  : formatNumber(lang, last.predicted_npv)
                : formatNumber(lang, last.verified_npv)}
            </p>
            <p className="jarvis-board-status">{last.status ?? DASH}</p>
          </>
        ) : (
          <p className="jarvis-board-missing">{last.reason ?? t('jarvis.boardNoRun')}</p>
        )}
      </section>
      <section className="jarvis-board-block">
        <p className="jarvis-board-label">{t('jarvis.boardNow')}</p>
        <p className="jarvis-board-now">
          {board.scenario} · {t('jarvis.contextStep')} {board.step}
          {board.date === null ? '' : ` · ${board.date}`}
        </p>
        <p className="jarvis-board-data">{board.data}</p>
      </section>
      {board.alerts.length === 0 ? null : (
        <section className="jarvis-board-block">
          <p className="jarvis-board-label">{t('jarvis.boardAlerts')}</p>
          <ul className="jarvis-board-alerts">
            {board.alerts.map((alert, index) => (
              <li key={`${alert.pattern ?? index}`} data-severity={alert.severity ?? 'info'}>
                <span>{alert.name ?? alert.pattern ?? DASH}</span>
                <span className="jarvis-board-alert-well">{alert.well ?? DASH}</span>
                {alert.step === null ? null : (
                  <span className="jarvis-board-alert-step">{alert.step}</span>
                )}
              </li>
            ))}
          </ul>
        </section>
      )}
    </div>
  );
};
