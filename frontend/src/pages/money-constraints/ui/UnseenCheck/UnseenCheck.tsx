import type { Translate } from '@/shared/i18n/I18nContext';
import type { Lang } from '@/shared/i18n/dictionaries';
import type { UnseenResult } from '@/pages/money-constraints/model/runTypes';
import {
  formatMoney,
  formatSignedPercent
} from '@/pages/money-constraints/ui/runMoney';

const METRICS: readonly [string, string][] = [
  ['oil_mass_delta', 'runs.unseenOil'],
  ['liquid_volume_delta', 'runs.unseenLiquid'],
  ['injection_volume_delta', 'runs.unseenInjection']
];

interface UnseenCheckProps {
  result: UnseenResult;
  lang: Lang;
  t: Translate;
}

export const UnseenCheck = ({ result, lang, t }: UnseenCheckProps) => {
  const year = result.yearly[result.focus_year] ?? {};
  const paired = result.paired_comparison;

  return (
    <section aria-label={t('runs.unseenLabel')}>
      <h4>{t('runs.unseenTitle')}</h4>
      {!result.exact_fit_overlap && (
        <p>
          {t('runs.unseenNoOverlap', { count: result.fitted_schedule_hashes_count })}
        </p>
      )}
      <p>{t('runs.unseenErrors', { year: result.focus_year })}</p>
      <ul>
        {METRICS.map(([key, label]) => {
          const percent = formatSignedPercent(lang, year[key]?.absolute_error_pct);
          return (
            <li key={key}>
              {t(label)}: {percent ?? t('runs.notMeasured')}
            </li>
          );
        })}
      </ul>
      {paired !== undefined && (
        <p>
          {t('runs.unseenPaired', {
            predicted: formatMoney(lang, paired.predicted_npv_change_rub) ?? '',
            measured: formatMoney(lang, paired.opm_npv_change_rub) ?? ''
          })}
        </p>
      )}
      <p className="scenarios-note">{t('runs.unseenNote')}</p>
    </section>
  );
};
