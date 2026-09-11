import { useEffect, useMemo, useState } from 'react';
import type { HierarchyIndexFile, HierarchyStep } from '@/entities/hierarchy/types';
import { useDataset, useHierarchyStep } from '@/entities';
import { useI18n } from '@/shared/i18n/I18nContext';
import { useTimeline } from '@/entities/timeline/model/TimelineContext';
import { ViewStatus } from '@/shared/ui/ViewStatus';
import { CouncilControls } from '@/pages/council/ui/CouncilControls/CouncilControls';
import { GroupLevel } from '@/pages/council/ui/GroupLevel/GroupLevel';
import {
  fieldSegments,
  groupCard,
  groupOrder,
  hasUngrouped,
  pathOf,
  ungroupedAllocations,
  wellsOf
} from '@/pages/council/model/levels';
import { WellLevel } from '@/pages/council/ui/WellLevel/WellLevel';
import './Council.css';

interface ReadyProps {
  data: HierarchyIndexFile;
  step: HierarchyStep | null;
}

const CouncilReady = ({ data, step }: ReadyProps) => {
  const { t } = useI18n();
  const { stepIndex, selectedWell, selectWell } = useTimeline();
  const [openGroup, setOpenGroup] = useState<string | null>(data.groups[0] ?? null);

  const order = useMemo(() => groupOrder(data), [data]);
  const segments = useMemo(
    () => (step === null ? [] : fieldSegments(step, order)),
    [step, order]
  );
  const cards = useMemo(
    () => (step === null ? [] : step.groups.map((level) => groupCard(level, order))),
    [step, order]
  );
  const ungrouped = useMemo(
    () => (step === null ? [] : ungroupedAllocations(step)),
    [step]
  );
  const showUngrouped = useMemo(
    () => (step === null ? false : hasUngrouped(data, step)),
    [data, step]
  );
  const path = useMemo(
    () => (step === null ? null : pathOf(step, selectedWell)),
    [step, selectedWell]
  );

  useEffect(() => {
    if (path !== null) {
      setOpenGroup(path.group);
    }
  }, [path]);

  const rows = useMemo(
    () => (step === null ? [] : wellsOf(step, openGroup, order)),
    [step, openGroup, order]
  );

  if (step === null) {
    return (
      <ViewStatus
        kind="error"
        title={t('council.desync')}
        hint={t('council.desyncHint', { step: stepIndex + 1, total: data.step_count })}
      />
    );
  }

  const synthetic = data.meta?.synthetic === true;
  const provenance = data.meta?.provenance ?? null;

  return (
    <section className="council" data-step={step.control_step}>
      <CouncilControls />
      {synthetic && (
        <p className="council-notice" role="note" data-testid="council-synthetic">
          <span className="council-notice-title">{t('council.synthetic.title')}</span>
          <span className="council-notice-body">
            {provenance === null
              ? t('council.synthetic.bodyUnknown')
              : t('council.synthetic.body', { provenance })}
          </span>
        </p>
      )}
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
  const { stepIndex } = useTimeline();
  const index = useDataset('hierarchy-index');
  const template = index.status === 'ready' ? index.data.step_path : null;
  const bounded =
    index.status === 'ready' && stepIndex < index.data.step_count ? stepIndex : null;
  const step = useHierarchyStep(template, bounded);

  if (index.status === 'loading') {
    return <ViewStatus kind="loading" title={t('council.loading')} />;
  }
  if (index.status === 'error') {
    return (
      <ViewStatus kind="error" title={t('council.error')} hint={t('council.errorHint')} />
    );
  }
  if (index.data.step_count === 0) {
    return <ViewStatus kind="empty" title={t('council.empty')} hint={t('council.emptyHint')} />;
  }
  if (bounded !== null && step.status === 'loading') {
    return <ViewStatus kind="loading" title={t('council.loading')} />;
  }

  return (
    <CouncilReady
      data={index.data}
      step={step.status === 'ready' ? step.data : null}
    />
  );
};
