import { useDataset } from '@/entities';
import { useT } from '@/shared/i18n/I18nContext';
import { ViewStatus } from '@/shared/ui/ViewStatus';
import { ScenarioComparison } from '@/pages/money-comparison/ui/ScenarioComparison/ScenarioComparison';
import { ScenarioLibrary } from '@/pages/money-comparison/ui/ScenarioLibrary/ScenarioLibrary';
import { MoneyProvenance } from '@/pages/money-comparison/ui/MoneyProvenance/MoneyProvenance';
import { RunsPanel } from '@/pages/money-comparison/ui/RunsPanel/RunsPanel';
import './MoneyComparison.css';

export const MoneyComparison = () => {
  const t = useT();
  const index = useDataset('scenarios');

  return (
    <div className="money-comparison" data-testid="money-workspace">
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
      {index.status === 'ready' && (
        <>
          <ScenarioComparison entries={index.data.scenarios} />
          <MoneyProvenance entries={index.data.scenarios} meta={index.data.meta} />
        </>
      )}
      <RunsPanel />
      <ScenarioLibrary />
    </div>
  );
};
