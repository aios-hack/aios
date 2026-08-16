import { useI18n } from '../i18n/I18nContext';
import { useProvenance } from '../state/ProvenanceContext';
import './SyntheticBanner.css';

export const SyntheticBanner = () => {
  const { t } = useI18n();
  const { synthetic, provenance } = useProvenance();

  if (!synthetic) {
    return null;
  }

  return (
    <aside className="synthetic-banner" role="note">
      <span className="synthetic-banner-mark" aria-hidden="true" />
      <p className="synthetic-banner-text">
        <strong className="synthetic-banner-title">{t('synthetic.title')}</strong>
        <span className="synthetic-banner-note">{t('synthetic.note')}</span>
      </p>
      <code className="synthetic-banner-tag">{provenance}</code>
    </aside>
  );
};
