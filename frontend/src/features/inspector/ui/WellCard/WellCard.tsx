import { useMemo } from 'react';
import { useDataset } from '@/entities';
import { useI18n } from '@/shared/i18n/I18nContext';
import { useTimeline } from '@/entities/timeline/model/TimelineContext';
import { AskJarvis } from '@/features/ask-jarvis/ui';
import { ViewStatus } from '@/shared/ui/ViewStatus';
import { formatStepDate } from '@/shared/lib/format';
import { ConnectivityBlock } from '@/features/inspector/ui/WellCard/ConnectivityBlock/ConnectivityBlock';
import { HistoryBlock } from '@/features/inspector/ui/WellCard/HistoryBlock/HistoryBlock';
import { connectivityOf, neighbourThreshold } from '@/entities/wells/model/neighbours';
import { wellRowAt } from '@/features/inspector/ui/WellCard/wellSeries';
import { TraceBlock } from '@/features/inspector/ui/WellCard/TraceBlock/TraceBlock';
import { WellParams } from '@/features/inspector/ui/WellCard/WellParams/WellParams';
import './WellCard.css';

interface WellCardProps {
  well: string;
}

export const WellCard = ({ well }: WellCardProps) => {
  const { t, lang } = useI18n();
  const { timeline, trace, stepIndex, selectWell } = useTimeline();
  const graph = useDataset('graph');

  const graphData = graph.status === 'ready' ? graph.data : null;
  const connectivity = useMemo(() => {
    if (graphData === null) {
      return null;
    }
    return connectivityOf(well, graphData, neighbourThreshold(graphData.edges));
  }, [graphData, well]);

  const steps = timeline.status === 'ready' ? timeline.data.steps : null;
  const step = steps ? steps[Math.min(stepIndex, steps.length - 1)] : null;
  const column = useMemo(
    () => (timeline.status === 'ready' ? timeline.data.wells.indexOf(well) : -1),
    [timeline, well]
  );
  const row = wellRowAt(step, well, column);
  const records =
    step && trace.status === 'ready'
      ? (trace.data[well]?.[String(step.control_step)] ?? [])
      : [];

  return (
    <div className="wellcard" data-testid="wellcard">
      <p className="wellcard-ask">
        <AskJarvis
          question={t('askJarvis.well', { well, step: stepIndex + 1 })}
          testId={`ask-jarvis-well-${well}`}
        />
      </p>
      {step && steps && (
        <p className="wellcard-step">
          <span>
            {t('wellcard.step', {
              step: step.control_step + 1,
              total: steps.length
            })}
          </span>
          <span className="wellcard-step-date">{formatStepDate(lang, step.date)}</span>
        </p>
      )}
      {timeline.status === 'loading' && (
        <ViewStatus kind="loading" title={t('wellcard.loading')} />
      )}
      {timeline.status === 'error' && (
        <ViewStatus kind="error" title={t('wellcard.error')} />
      )}
      {step && !row && <ViewStatus kind="empty" title={t('wellcard.noData')} />}
      {row && (
        <>
          <section className="wellcard-section">
            <h4 className="wellcard-section-title">{t('wellcard.params.title')}</h4>
            <WellParams row={row} />
          </section>
          {timeline.status === 'ready' && (
            <HistoryBlock timeline={timeline.data} well={well} stepIndex={stepIndex} />
          )}
          <section className="wellcard-section">
            <h4 className="wellcard-section-title">{t('wellcard.neighbours.title')}</h4>
            {connectivity !== null && (
              <ConnectivityBlock connectivity={connectivity} onSelect={selectWell} />
            )}
            {graph.status === 'loading' && (
              <p className="wellcard-empty">{t('wellcard.loading')}</p>
            )}
            {graph.status === 'error' && (
              <p className="wellcard-empty">{t('wellcard.neighbours.error')}</p>
            )}
          </section>
          <section className="wellcard-section">
            <h4 className="wellcard-section-title">{t('wellcard.decision.title')}</h4>
            {trace.status === 'ready' && step && (
              <TraceBlock records={records} well={well} step={step.control_step} />
            )}
            {trace.status === 'loading' && (
              <p className="wellcard-empty">{t('wellcard.loading')}</p>
            )}
            {trace.status === 'error' && (
              <p className="wellcard-empty">{t('wellcard.decision.error')}</p>
            )}
          </section>
          <section className="wellcard-section">
            <h4 className="wellcard-section-title">{t('wellcard.explanation.title')}</h4>
            {row.explanation ? (
              <p className="wellcard-explanation">{row.explanation}</p>
            ) : (
              <p className="wellcard-empty">{t('wellcard.explanation.empty')}</p>
            )}
          </section>
        </>
      )}
    </div>
  );
};
