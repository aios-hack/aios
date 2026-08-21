import { useDataset } from '../../data';
import { useT } from '../../i18n/I18nContext';
import { useTimeline } from '../../state/TimelineContext';
import { ViewStatus } from '../../ui/ViewStatus';
import { ConstraintsEditor } from './ConstraintsEditor';
import { ScenarioComparison } from './ScenarioComparison';
import { ScenarioLibrary } from './ScenarioLibrary';
import './ScenariosLibrary.css';

export const Scenarios = () => {
  const t = useT();
  const { timeline } = useTimeline();
  const index = useDataset('scenarios');

  return (
    <div className="scenarios">
      {index.status === 'ready' && <ScenarioComparison entries={index.data.scenarios} />}
      <ScenarioLibrary />
      {timeline.status === 'ready' ? (
        <ConstraintsEditor nIntervals={timeline.data.n_intervals} />
      ) : (
        <ViewStatus
          kind={timeline.status === 'error' ? 'error' : 'loading'}
          title={
            timeline.status === 'error'
              ? t('scenarios.editor.horizonError')
              : t('scenarios.editor.horizonLoading')
          }
          hint={timeline.status === 'error' ? t('scenarios.editor.horizonHint') : undefined}
        />
      )}
    </div>
  );
};
