import { useEffect, useRef } from 'react';
import { useI18n } from '../../i18n/I18nContext';
import { useTimeline } from '../../state/TimelineContext';
import { formatStepDate } from '../Timeline/format';
import { TraceBlock } from './TraceBlock';
import { WellParams } from './WellParams';
import './WellCard.css';

export const WellCard = () => {
  const { t, lang } = useI18n();
  const { timeline, trace, stepIndex, selectedWell, selectWell } = useTimeline();
  const panelRef = useRef<HTMLElement | null>(null);

  useEffect(() => {
    if (selectedWell !== null) {
      panelRef.current?.focus();
    }
  }, [selectedWell]);

  useEffect(() => {
    if (selectedWell === null) {
      return;
    }
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        selectWell(null);
      }
    };
    window.addEventListener('keydown', onKeyDown);
    return () => window.removeEventListener('keydown', onKeyDown);
  }, [selectedWell, selectWell]);

  if (selectedWell === null) {
    return null;
  }

  const steps = timeline.status === 'ready' ? timeline.data.steps : null;
  const step = steps ? steps[Math.min(stepIndex, steps.length - 1)] : null;
  const row = step
    ? step.wells.find((well) => well.well === selectedWell) ?? null
    : null;
  const records =
    step && trace.status === 'ready'
      ? trace.data[selectedWell]?.[String(step.control_step)] ?? []
      : [];

  return (
    <aside
      ref={panelRef}
      tabIndex={-1}
      className="wellcard"
      aria-label={t('wellcard.title', { well: selectedWell })}
    >
      <header className="wellcard-header">
        <div>
          <h3 className="wellcard-title">
            {t('wellcard.title', { well: selectedWell })}
          </h3>
          {step && steps && (
            <p className="wellcard-step">
              <span>
                {t('wellcard.step', { step: step.control_step + 1, total: steps.length })}
              </span>
              <span className="wellcard-step-date">{formatStepDate(lang, step.date)}</span>
            </p>
          )}
        </div>
        <button
          type="button"
          className="wellcard-close"
          aria-label={t('wellcard.close')}
          onClick={() => selectWell(null)}
        >
          ×
        </button>
      </header>
      <div className="wellcard-body">
        {timeline.status === 'loading' && (
          <p className="wellcard-status">{t('wellcard.loading')}</p>
        )}
        {timeline.status === 'error' && (
          <p className="wellcard-status wellcard-status-error">{t('wellcard.error')}</p>
        )}
        {step && !row && <p className="wellcard-status">{t('wellcard.noData')}</p>}
        {row && (
          <>
            <section className="wellcard-section">
              <h4 className="wellcard-section-title">{t('wellcard.params.title')}</h4>
              <WellParams row={row} />
            </section>
            <section className="wellcard-section">
              <h4 className="wellcard-section-title">{t('wellcard.decision.title')}</h4>
              {trace.status === 'ready' && <TraceBlock records={records} />}
              {trace.status === 'loading' && (
                <p className="wellcard-empty">{t('wellcard.loading')}</p>
              )}
              {trace.status === 'error' && (
                <p className="wellcard-empty">{t('wellcard.decision.error')}</p>
              )}
            </section>
            <section className="wellcard-section">
              <h4 className="wellcard-section-title">
                {t('wellcard.explanation.title')}
              </h4>
              {row.explanation ? (
                <p className="wellcard-explanation">{row.explanation}</p>
              ) : (
                <p className="wellcard-empty">{t('wellcard.explanation.empty')}</p>
              )}
            </section>
          </>
        )}
      </div>
    </aside>
  );
};
