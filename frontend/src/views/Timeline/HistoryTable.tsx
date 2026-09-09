import { useMemo } from 'react';
import type { FieldNormBand, TimelineStep, TimelineWellRow } from '../../api/types';
import { useT } from '../../i18n/I18nContext';
import { useTimeline } from '../../state/TimelineContext';
import { ViewStatus } from '../../ui/ViewStatus';
import { CompensationPanel } from './CompensationPanel';
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

  const step = useMemo((): TimelineStep | undefined => {
    if (timeline.status !== 'ready') {
      return undefined;
    }
    const current = Math.min(stepIndex, timeline.data.steps.length - 1);
    return timeline.data.steps[current];
  }, [timeline, stepIndex]);

  const band = useMemo((): FieldNormBand | null => {
    if (timeline.status !== 'ready') {
      return null;
    }
    return timeline.data.field_norms?.compensation ?? null;
  }, [timeline]);

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
      <CompensationPanel step={step} band={band} />
      <WellsTable wells={wellsAtStep} selectedWell={selectedWell} onSelectWell={selectWell} />
    </div>
  );
};
