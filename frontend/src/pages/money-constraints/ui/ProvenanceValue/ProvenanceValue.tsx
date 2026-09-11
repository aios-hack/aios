import type { Translate } from '@/shared/i18n/I18nContext';
import type { Lang } from '@/shared/i18n/dictionaries';
import { formatNumber } from '@/shared/lib/format';
import {
  candidateKeyOf,
  HASH_FIELDS,
  isEquilibriumUnclaimed,
  strategyKeyOf
} from '@/pages/money-constraints/model/runFields';
import { ProvenanceHash } from '@/pages/money-constraints/ui/ProvenanceHash/ProvenanceHash';

interface ProvenanceValueProps {
  name: string;
  value: unknown;
  lang: Lang;
  t: Translate;
}

export const ProvenanceValue = ({ name, value, lang, t }: ProvenanceValueProps) => {
  if (value === null || value === undefined || value === '') {
    return <span className="run-provenance-absent">{t('runs.notRecorded')}</span>;
  }
  if (typeof value === 'boolean') {
    return <>{value ? t('runs.yes') : t('runs.no')}</>;
  }
  if (typeof value === 'number') {
    return <>{formatNumber(lang, value, 0)}</>;
  }
  const text = String(value);
  if (HASH_FIELDS.has(name)) {
    return <ProvenanceHash value={text} />;
  }
  if (name === 'search_strategy') {
    const key = strategyKeyOf(text);
    return <>{key === null ? text : t(`runs.strategy.${key}`)}</>;
  }
  if (name === 'selected_candidate') {
    const key = candidateKeyOf(text);
    return <>{key === null ? text : t(`runs.candidate.${key}`)}</>;
  }
  if (name === 'policy_equilibrium' && isEquilibriumUnclaimed(text)) {
    return <>{t('runs.equilibriumUnclaimed')}</>;
  }
  return <>{text}</>;
};
