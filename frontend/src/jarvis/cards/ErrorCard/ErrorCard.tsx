import { useT } from '@/shared/i18n/I18nContext';
import { translateOr } from '@/jarvis/i18nFallback';
import { useOptionalJarvisSession } from '@/jarvis/provider/contexts';
import { readError } from '@/jarvis/cards/payloads/cardPayloads';
import './ErrorCard.css';

export const ErrorCard = ({ payload }: { payload: unknown }) => {
  const t = useT();
  const jarvis = useOptionalJarvisSession();
  const failure = readError(payload);

  return (
    <div className="jarvis-error" role="status">
      <p className="jarvis-error-title">{t('jarvis-cards.errorTitle')}</p>
      <p className="jarvis-error-reason">
        {translateOr(t, `jarvis-screen.error.${failure.code}`, 'jarvis-screen.error.unknown')}
      </p>
      {failure.tool === null ? null : <p className="jarvis-error-tool">{failure.tool}</p>}
      {jarvis === null ? null : (
        <button type="button" className="jarvis-error-retry" onClick={jarvis.retry}>
          {t('jarvis-screen.retry')}
        </button>
      )}
    </div>
  );
};
