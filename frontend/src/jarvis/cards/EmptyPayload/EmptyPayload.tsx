import { useT } from '@/shared/i18n/I18nContext';
import './EmptyPayload.css';

export const EmptyPayload = () => {
  const t = useT();
  return <p className="jarvis-empty-payload">{t('jarvis-cards.badPayload')}</p>;
};
