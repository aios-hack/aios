import { useT } from '../../i18n/I18nContext';
import './EmptyPayload.css';

export const EmptyPayload = () => {
  const t = useT();
  return <p className="jarvis-empty-payload">{t('jarvis.badPayload')}</p>;
};
