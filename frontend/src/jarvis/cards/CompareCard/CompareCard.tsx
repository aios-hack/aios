import { DASH, formatNumber } from '@/shared/lib/format';
import { useI18n } from '@/shared/i18n/I18nContext';
import { readCompare } from '@/jarvis/cards/payloads/cardPayloads';
import type { CompareConstraints, CompareStatus } from '@/jarvis/cards/payloads/payloadTypes';
import { EmptyPayload } from '@/jarvis/cards/EmptyPayload/EmptyPayload';
import './CompareCard.css';

const flagKeys = (status: CompareStatus): { key: string; on: boolean }[] => {
  const collected: { key: string; on: boolean }[] = [];
  if (status.sound !== null) {
    collected.push({ key: 'jarvis-cards.compareSound', on: status.sound });
  }
  if (status.converged !== null) {
    collected.push({ key: 'jarvis-cards.compareConverged', on: status.converged });
  }
  if (status.self_consistent !== null) {
    collected.push({ key: 'jarvis-cards.compareConsistent', on: status.self_consistent });
  }
  if (status.has_submission !== null) {
    collected.push({ key: 'jarvis-cards.compareSubmitted', on: status.has_submission });
  }
  return collected;
};

const constraintCount = (constraints: CompareConstraints): string =>
  constraints.total === null ? DASH : String(constraints.total);

export const CompareCard = ({ payload }: { payload: unknown }) => {
  const { lang, t } = useI18n();
  const compare = readCompare(payload);
  if (compare === null) {
    return <EmptyPayload />;
  }
  const delta = compare.delta_npv;

  return (
    <div className="jarvis-compare">
      <div className="jarvis-compare-sides">
        {[compare.a, compare.b].map((side) => (
          <div className="jarvis-compare-side" key={side.id}>
            <p className="jarvis-compare-id">{side.id}</p>
            <p className="jarvis-compare-npv">
              {side.npv === null ? DASH : formatNumber(lang, side.npv)}
            </p>
            <p className="jarvis-compare-status">
              {side.status.status ?? side.status.opm_status ?? DASH}
            </p>
            <ul className="jarvis-compare-flags">
              {flagKeys(side.status).map((flag) => (
                <li key={flag.key} data-on={flag.on ? 'true' : 'false'}>
                  {t(flag.key)}
                </li>
              ))}
            </ul>
            {side.status.ood_score === null ? null : (
              <p className="jarvis-compare-ood">
                {t('jarvis-cards.compareOod')}: {formatNumber(lang, side.status.ood_score, 2)}
                {side.status.ood_threshold === null
                  ? ''
                  : ` / ${formatNumber(lang, side.status.ood_threshold, 2)}`}
              </p>
            )}
            <p className="jarvis-compare-meta">
              <span>
                {t('jarvis-cards.compareConstraints')}: {constraintCount(side.constraints)}
              </span>
            </p>
            {side.constraints.groups.length === 0 ? null : (
              <ul className="jarvis-compare-groups">
                {side.constraints.groups
                  .filter((group) => group.count > 0)
                  .map((group) => (
                    <li key={group.key}>
                      <span>{group.key}</span>
                      <span>{group.count}</span>
                    </li>
                  ))}
              </ul>
            )}
          </div>
        ))}
      </div>
      <p className="jarvis-compare-delta" data-sign={(delta ?? 0) >= 0 ? 'up' : 'down'}>
        <span className="jarvis-compare-delta-label">{t('jarvis-cards.compareDelta')}</span>
        {delta === null ? DASH : formatNumber(lang, delta)}
      </p>
      {compare.top_diff_wells.length === 0 ? (
        compare.comparison_reason === null ? null : (
          <p className="jarvis-compare-reason">{compare.comparison_reason}</p>
        )
      ) : (
        <div className="jarvis-compare-wells">
          <p className="jarvis-compare-wells-label">{t('jarvis-cards.compareTopWells')}</p>
          <ol className="jarvis-compare-well-list">
            {compare.top_diff_wells.map((row) => (
              <li key={row.well} data-sign={row.delta >= 0 ? 'up' : 'down'}>
                <span className="jarvis-compare-well">{row.well}</span>
                <span className="jarvis-compare-well-delta">
                  {formatNumber(lang, row.delta)}
                </span>
              </li>
            ))}
          </ol>
        </div>
      )}
    </div>
  );
};
