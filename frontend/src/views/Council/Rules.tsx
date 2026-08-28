import { useDataset } from '../../data';
import { useT } from '../../i18n/I18nContext';
import { ViewStatus } from '../../ui/ViewStatus';
import { AblationTable } from '../NpvRank/AblationTable';

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

  return <AblationTable data={ablation.data} standalone />;
};
