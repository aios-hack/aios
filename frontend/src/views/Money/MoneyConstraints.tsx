import { useT } from '../../i18n/I18nContext';
import { useTimeline } from '../../state/TimelineContext';
import { ViewStatus } from '../../ui/ViewStatus';
import { ConstraintsEditor } from '../Scenarios/ConstraintsEditor';

export const MoneyConstraints = () => {
  const t = useT();
  const { timeline } = useTimeline();

  if (timeline.status !== 'ready') {
    return (
      <ViewStatus
        kind={timeline.status === 'error' ? 'error' : 'loading'}
        title={
          timeline.status === 'error'
            ? t('scenarios.editor.horizonError')
            : t('scenarios.editor.horizonLoading')
        }
        hint={timeline.status === 'error' ? t('scenarios.editor.horizonHint') : undefined}
      />
    );
  }

  return <ConstraintsEditor nIntervals={timeline.data.n_intervals} />;
};
