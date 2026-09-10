import { useEffect, useState } from 'react';
import { useI18n } from '../../i18n/I18nContext';
import { useJarvis } from '../JarvisContext';
import { fetchSessionRows, type SessionRow } from '../sessions';
import { sessionDayKey } from './cardGlyphs';
import './HistorySessions.css';

const NEW = '';

export const HistorySessions = () => {
  const { lang, t } = useI18n();
  const { sessionId, loadSession, startSession, visible, scenes } = useJarvis();
  const [rows, setRows] = useState<SessionRow[]>([]);

  useEffect(() => {
    if (!visible) {
      return;
    }
    let alive = true;
    void fetchSessionRows().then((next) => {
      if (alive) {
        setRows(next);
      }
    });
    return () => {
      alive = false;
    };
  }, [visible, scenes.scenes.length]);

  const known = rows.some((row) => row.id === sessionId);
  const today = new Date();

  return (
    <label className="jarvis-sessions">
      <span className="jarvis-sessions-label">{t('jarvis.sessionsLabel')}</span>
      <select
        className="jarvis-sessions-select"
        value={known ? sessionId : NEW}
        onChange={(event) => {
          const picked = event.target.value;
          if (picked === NEW) {
            startSession();
            return;
          }
          loadSession(picked);
        }}
      >
        <option value={NEW}>{t('jarvis.sessionNew')}</option>
        {rows.map((row) => {
          const day = sessionDayKey(lang, row.last, today);
          const when =
            day === 'today'
              ? t('jarvis.sessionToday')
              : day === 'yesterday'
                ? t('jarvis.sessionYesterday')
                : day;
          const question =
            row.first_question.length === 0 ? t('jarvis.sessionNoQuestion') : row.first_question;
          return (
            <option value={row.id} key={row.id}>
              {when} · {question}
            </option>
          );
        })}
      </select>
    </label>
  );
};
