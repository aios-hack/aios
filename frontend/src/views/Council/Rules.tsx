import { useDataset } from '../../data';
import { useT } from '../../i18n/I18nContext';
import { ViewStatus } from '../../ui/ViewStatus';
import { AblationTable } from '../NpvRank/AblationTable';
import './Rules.css';

export const Rules = () => {
  const t = useT();
  const ablation = useDataset('ablation');

  if (ablation.status === 'loading') {
    return <ViewStatus kind="loading" title={t('npv.ablation.loading')} />;
  }
  if (ablation.status === 'error') {
    return (
      <ViewStatus
        kind="error"
        title={t('npv.ablation.error')}
        hint={t('npv.ablation.errorHint')}
      />
    );
  }

  const measured = ablation.data.rules.some((rule) => rule.delta_npv !== null);

  return (
    <div className="rules">
      {!measured && (
        <p className="rules-notice" role="note" data-testid="rules-not-measured">
          <span className="rules-notice-title">{t('npv.ablation.notRun.title')}</span>
          <span className="rules-notice-body">{t('npv.ablation.notRun.body')}</span>
        </p>
      )}
      <AblationTable data={ablation.data} standalone />
    </div>
  );
};
