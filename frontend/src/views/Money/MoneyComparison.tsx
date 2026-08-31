import { useDataset } from '../../data';
import { useT } from '../../i18n/I18nContext';
import { ViewStatus } from '../../ui/ViewStatus';
import { ScenarioComparison } from '../Scenarios/ScenarioComparison';
import { ScenarioLibrary } from '../Scenarios/ScenarioLibrary';

export const MoneyComparison = () => {
  const t = useT();
  const index = useDataset('scenarios');

  return (
    <div className="money-comparison">
      {index.status === 'loading' && (
        <ViewStatus kind="loading" title={t('scenarios.compare.loading')} />
      )}
      {index.status === 'error' && (
        <ViewStatus
          kind="error"
          title={t('scenarios.compare.error')}
          hint={t('scenarios.library.errorHint')}
        />
      )}
      {index.status === 'ready' && <ScenarioComparison entries={index.data.scenarios} />}
      <ScenarioLibrary />
    </div>
  );
};
