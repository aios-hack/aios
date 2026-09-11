import { useCallback } from 'react';
import type { TraceRecord } from '@/entities/trace/types';
import { useI18n } from '@/shared/i18n/I18nContext';
import { useTimeline } from '@/entities/timeline/model/TimelineContext';
import { useOptionalJarvisSession } from '@/jarvis/provider/contexts';
import { explainEvents, type ExplainFact } from '@/jarvis/actions/lib/explainScene';

export interface ExplainTarget {
  well: string;
  step: number;
}

export const useExplainAction = (): ((target: ExplainTarget) => void) | null => {
  const jarvis = useOptionalJarvisSession();
  const { t } = useI18n();
  const { timeline, trace } = useTimeline();

  const run = useCallback(
    (target: ExplainTarget) => {
      if (jarvis === null) {
        return;
      }
      const steps = timeline.status === 'ready' ? timeline.data.steps : [];
      const step = steps[target.step];
      const records: TraceRecord[] =
        trace.status === 'ready'
          ? (trace.data[target.well]?.[String(target.step)] ?? [])
          : [];
      jarvis.pushEvents(
        explainEvents({
          well: target.well,
          step: target.step,
          date: step?.date ?? '',
          records,
          context: { ...jarvis.askContext, step: target.step, selected_well: target.well },
          provenance: 'trace',
          question: t('jarvis-stage.explainQuestion', { well: target.well }),
          ruleName: (rule: string) => t(`council.rule.${rule}`),
          caption: (facts: ExplainFact[]) =>
            t('jarvis-stage.explainCaption', {
              well: target.well,
              rules: facts.map((fact) => fact.rule).join(', '),
              decision: facts[0].decision
            }),
          noEntryTitle: t('jarvis-stage.explainNoEntryTitle'),
          noEntryMessage: t('jarvis-stage.explainNoEntry', { well: target.well }),
          cardTitle: (rule: string, well: string) =>
            t('jarvis-stage.explainCardTitle', { rule, well })
        })
      );
      jarvis.open();
    },
    [jarvis, timeline, trace, t]
  );

  return jarvis === null ? null : run;
};
