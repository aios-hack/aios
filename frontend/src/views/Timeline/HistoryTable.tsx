import { useMemo } from 'react';
import type { TimelineWellRow } from '../../api/types';
import { useHistoryView } from '../../app/HistoryViewContext';
import { dataOf, useDataset } from '../../data';
import { useT } from '../../i18n/I18nContext';
import { useTimeline } from '../../state/TimelineContext';
import { ViewStatus } from '../../ui/ViewStatus';
import { groupByWell, lastWatercutByWell, npvByWell, sortWellRows } from '../shared/wellFacts';
import { HistoryTableControls } from './HistoryTableControls';
import { WellsTable } from './WellsTable';

export const HistoryTable = () => {
  const t = useT();
  const { timeline, stepIndex, selectedWell, selectWell } = useTimeline();
  const npvState = useDataset('npv');
  const graphState = useDataset('graph');
  const { metric, setMetric, sort, setSort } = useHistoryView();

  const npv = useMemo(() => npvByWell(dataOf(npvState)), [npvState]);
  const groups = useMemo(() => groupByWell(dataOf(graphState)), [graphState]);

  const orderedWells = useMemo((): TimelineWellRow[] => {
    if (timeline.status !== 'ready') {
      return [];
    }
    const watercut = lastWatercutByWell(timeline.data);
    const order = sortWellRows(
      timeline.data.wells.map((well) => ({
        well,
        group: groups.get(well) ?? null,
        npv: npv.get(well),
        watercut: watercut.get(well)
      })),
      sort
    ).map((row) => row.well);
    const current = Math.min(stepIndex, timeline.data.steps.length - 1);
    const byWell = new Map(
      timeline.data.steps[current]?.wells.map((row) => [row.well, row])
    );
    return order
      .map((well) => byWell.get(well))
      .filter((row): row is TimelineWellRow => row !== undefined);
  }, [timeline, stepIndex, groups, npv, sort]);

  if (timeline.status === 'loading') {
    return <ViewStatus kind="loading" title={t('steps.loading')} />;
  }
  if (timeline.status === 'error') {
    return <ViewStatus kind="error" title={t('steps.error')} hint={t('steps.errorHint')} />;
  }
  if (timeline.data.steps.length === 0) {
    return null;
  }

  return (
    <div className="history-table" data-testid="history-table">
      <HistoryTableControls metric={metric} onMetric={setMetric} sort={sort} onSort={setSort} />
      <WellsTable wells={orderedWells} selectedWell={selectedWell} onSelectWell={selectWell} />
    </div>
  );
};
