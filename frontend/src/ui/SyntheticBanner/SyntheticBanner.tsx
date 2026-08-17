import { useI18n } from '../../i18n/I18nContext';
import { useProvenance } from '../../state/ProvenanceContext';
import { InfoHint } from '../InfoHint';
import './SyntheticBanner.css';

export const SyntheticBanner = () => {
  const { t } = useI18n();
  const { synthetic, provenance } = useProvenance();

  if (!synthetic) {
    return null;
  }

  return (
    <span className="synthetic-mark" data-provenance={provenance}>
      <span className="synthetic-mark-text">{t('synthetic.short')}</span>
      <InfoHint label={t('synthetic.title')} text={t('synthetic.note')} />
    </span>
  );
};
