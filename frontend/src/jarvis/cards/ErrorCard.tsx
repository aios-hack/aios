import { useT } from '../../i18n/I18nContext';
import { translateOr } from '../i18nFallback';
import { readError } from './cardPayloads';
import './ErrorCard.css';

export const ErrorCard = ({ payload }: { payload: unknown }) => {
  const t = useT();
  const failure = readError(payload);

  return (
    <div className="jarvis-error" role="status">
      <p className="jarvis-error-title">{t('jarvis.errorTitle')}</p>
      <p className="jarvis-error-reason">{translateOr(t, `jarvis.error.${failure.code}`, 'jarvis.error.unknown')}</p>
      {failure.tool === null ? null : (
        <p className="jarvis-error-tool">{failure.tool}</p>
      )}
    </div>
  );
};
