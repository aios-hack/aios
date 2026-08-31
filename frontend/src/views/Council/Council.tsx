import { useEffect, useMemo, useState } from 'react';
import type { HierarchyFile } from '../../api/types';
import { useDataset } from '../../data';
import { useI18n } from '../../i18n/I18nContext';
import { useTimeline } from '../../state/TimelineContext';
import { ViewStatus } from '../../ui/ViewStatus';
import { CouncilControls } from './CouncilControls';
import { GroupLevel } from './GroupLevel';
import {
  fieldSegments,
  groupCard,
  groupOrder,
  hasUngrouped,
  pathOf,
  stepAt,
  ungroupedAllocations,
  wellsOf
} from './levels';
import { WellLevel } from './WellLevel';
import './Council.css';

const CouncilReady = ({ data }: { data: HierarchyFile }) => {
  const { stepIndex, selectedWell, selectWell } = useTimeline();
  const [openGroup, setOpenGroup] = useState<string | null>(data.groups[0] ?? null);

  const order = useMemo(() => groupOrder(data), [data]);
  const step = useMemo(() => stepAt(data, stepIndex), [data, stepIndex]);
  const segments = useMemo(() => fieldSegments(step, order), [step, order]);
  const cards = useMemo(
    () => step.groups.map((level) => groupCard(level, order)),
    [step, order]
  );
  const ungrouped = useMemo(() => ungroupedAllocations(step), [step]);
  const showUngrouped = useMemo(() => hasUngrouped(data, step), [data, step]);
  const path = useMemo(() => pathOf(step, selectedWell), [step, selectedWell]);

  useEffect(() => {
    if (path !== null) {
      setOpenGroup(path.group);
    }
  }, [path]);

  const rows = useMemo(() => wellsOf(step, openGroup, order), [step, openGroup, order]);

  return (
    <section className="council" data-step={step.control_step}>
      <CouncilControls />
      <GroupLevel
        step={step}
        segments={segments}
        cards={cards}
        ungrouped={ungrouped}
        showUngrouped={showUngrouped}
        path={path}
        activeGroup={openGroup}
        onSelectGroup={setOpenGroup}
        onSelectWell={selectWell}
      />
      <WellLevel
        rows={rows}
        groupLabel={openGroup}
        path={path}
        onSelectWell={selectWell}
      />
    </section>
  );
};

export const Council = () => {
  const { t } = useI18n();
  const hierarchy = useDataset('hierarchy');

  if (hierarchy.status === 'loading') {
    return <ViewStatus kind="loading" title={t('council.loading')} />;
  }
  if (hierarchy.status === 'error') {
    return (
      <ViewStatus kind="error" title={t('council.error')} hint={t('council.errorHint')} />
    );
  }
  if (hierarchy.data.steps.length === 0) {
    return <ViewStatus kind="empty" title={t('council.empty')} hint={t('council.emptyHint')} />;
  }

  return <CouncilReady data={hierarchy.data} />;
};
