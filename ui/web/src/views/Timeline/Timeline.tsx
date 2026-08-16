import { useEffect, useState } from 'react';
import { useT } from '../../i18n/I18nContext';
import { useTimeline } from '../../state/TimelineContext';
import { ViewStatus } from '../../ui/ViewStatus';
import { FieldStats } from './FieldStats';
import { StepControls } from './StepControls';
import { WellsTable } from './WellsTable';
import './Timeline.css';

const PLAY_INTERVAL_MS = 300;

export const Timeline = () => {
  const t = useT();
  const { timeline, stepIndex, setStepIndex, selectedWell, selectWell } = useTimeline();
  const [playing, setPlaying] = useState(false);

  const stepCount = timeline.status === 'ready' ? timeline.data.steps.length : 0;

  useEffect(() => {
    if (!playing || stepCount === 0) {
      return;
    }
    const id = window.setInterval(() => {
      setStepIndex((current) => Math.min(current + 1, stepCount - 1));
    }, PLAY_INTERVAL_MS);
    return () => window.clearInterval(id);
  }, [playing, stepCount, setStepIndex]);

  useEffect(() => {
    if (playing && stepCount > 0 && stepIndex >= stepCount - 1) {
      setPlaying(false);
    }
  }, [playing, stepIndex, stepCount]);

  if (timeline.status === 'loading') {
    return <ViewStatus kind="loading" title={t('steps.loading')} />;
  }
  if (timeline.status === 'error') {
    return <ViewStatus kind="error" title={t('steps.error')} hint={t('steps.errorHint')} />;
  }

  const steps = timeline.data.steps;
  const current = Math.min(stepIndex, steps.length - 1);
  const step = steps[current];

  const selectStep = (index: number) => {
    setPlaying(false);
    setStepIndex(Math.min(Math.max(index, 0), steps.length - 1));
  };

  const togglePlay = () => {
    if (!playing && current >= steps.length - 1) {
      setStepIndex(0);
    }
    setPlaying((value) => !value);
  };

  return (
    <section className="timeline">
      <StepControls
        steps={steps}
        stepIndex={current}
        playing={playing}
        onSelect={selectStep}
        onStep={(delta) => selectStep(current + delta)}
        onTogglePlay={togglePlay}
      />
      <FieldStats field={step.field} />
      <WellsTable
        wells={step.wells}
        selectedWell={selectedWell}
        onSelectWell={selectWell}
      />
    </section>
  );
};
