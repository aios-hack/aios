import { useMemo } from 'react';
import type { TimelineWellRow } from '../../api/types';
import { useT } from '../../i18n/I18nContext';
import { useTimeline } from '../../state/TimelineContext';
import { ViewStatus } from '../../ui/ViewStatus';
import { HistoryTableControls } from './HistoryTableControls';
import { WellsTable } from './WellsTable';

export const HistoryTable = () => {
  const t = useT();
  const { timeline, stepIndex, selectedWell, selectWell } = useTimeline();

  const wellsAtStep = useMemo((): TimelineWellRow[] => {
    if (timeline.status !== 'ready') {
      return [];
    }
    const current = Math.min(stepIndex, timeline.data.steps.length - 1);
    return timeline.data.steps[current]?.wells ?? [];
  }, [timeline, stepIndex]);

  if (timeline.status === 'loading') {
    return <ViewStatus kind="loading" title={t('steps.loading')} />;
  }
  if (timeline.status === 'error') {
    return <ViewStatus kind="error" title={t('steps.error')} hint={t('steps.errorHint')} />;
  }
  if (timeline.data.steps.length === 0) {
    return <ViewStatus kind="empty" title={t('steps.empty')} />;
  }

  return (
    <div className="history-table" data-testid="history-table">
      <HistoryTableControls />
      <WellsTable wells={wellsAtStep} selectedWell={selectedWell} onSelectWell={selectWell} />
    </div>
  );
};
