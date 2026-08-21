import { memo, useMemo } from 'react';
import type { AblationFile } from '../../api/types';
import { useI18n } from '../../i18n/I18nContext';
import { formatNumber, formatPercent } from '../../ui/format';
import { coverageOf, toEntries } from './ablation';
import { AblationRow } from './AblationRow';
import './AblationTable.css';

interface AblationTableProps {
  data: AblationFile;
}

const AblationTableView = ({ data }: AblationTableProps) => {
  const { t, lang } = useI18n();
  const entries = useMemo(() => toEntries(data.rules), [data.rules]);
  const coverage = useMemo(() => coverageOf(entries), [entries]);

  return (
    <section className="abl" aria-labelledby="abl-title">
      <header className="abl-head">
        <h3 className="abl-title" id="abl-title">
          {t('npv.ablation.title')}
        </h3>
        <p className="abl-intro">{t('npv.ablation.intro')}</p>
        <p className="abl-total">
          <span className="abl-total-label">{t('npv.ablation.total')}</span>
          <span className="abl-total-amount">
            <span className="abl-total-value" data-testid="abl-total">
              {formatNumber(lang, data.npv_total)}
            </span>
            <span className="abl-total-unit">{t('npv.ablation.totalUnit')}</span>
          </span>
        </p>
        <p className="abl-coverage" data-testid="abl-coverage">
          {t('npv.ablation.coverage', {
            share: formatPercent(lang, coverage.accountedShare),
            measured: coverage.measured,
            total: entries.length
          })}
          {coverage.unmeasured > 0 && (
            <span className="abl-coverage-gap">
              {t('npv.ablation.coverageGap', { count: coverage.unmeasured })}
            </span>
          )}
        </p>
      </header>
      <div className="abl-table-wrap">
        <table className="abl-table">
          <thead>
            <tr>
              <th scope="col">{t('npv.ablation.column.rule')}</th>
              <th scope="col">{t('npv.ablation.column.statement')}</th>
              <th scope="col">{t('npv.ablation.column.flag')}</th>
              <th scope="col" className="abl-cell-num">
                {t('npv.ablation.column.delta')}
              </th>
              <th scope="col" className="abl-cell-bar">
                {t('npv.ablation.column.share')}
              </th>
            </tr>
          </thead>
          <tbody>
            {entries.map((entry) => (
              <AblationRow key={entry.rule} entry={entry} lang={lang} t={t} />
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
};

export const AblationTable = memo(AblationTableView);
