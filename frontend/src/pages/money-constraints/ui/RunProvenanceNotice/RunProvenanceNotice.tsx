import { useFallbackI18n } from '@/shared/i18n/I18nContext';
import type { RunManifest } from '@/entities/runs/model/runTypes';
import {
  isEquilibriumUnclaimed,
  isFallbackStrategy
} from '@/pages/money-constraints/ui/runFields';

export const RunProvenanceNotice = ({
  manifest
}: {
  manifest: RunManifest | undefined;
}) => {
  const { t } = useFallbackI18n();
  const fallback = isFallbackStrategy(manifest?.search_strategy);
  const unclaimed = isEquilibriumUnclaimed(manifest?.policy_equilibrium);
  if (!fallback && !unclaimed) {
    return null;
  }
  return (
    <p className="scenarios-banner run-provenance-notice" role="note">
      {fallback ? t('runs.noticeFallback') : t('runs.noticeUnclaimed')} {t('runs.noticeTail')}
    </p>
  );
};
