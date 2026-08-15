import { useEffect, useState } from 'react';
import type { TimelineFile } from '../../api/types';
import { useT } from '../../i18n/I18nContext';
import { FieldStats } from './FieldStats';
import { StepControls } from './StepControls';
import { WellsTable } from './WellsTable';
import './Timeline.css';

const PLAY_INTERVAL_MS = 300;

type LoadState =
  | { status: 'loading' }
  | { status: 'error' }
  | { status: 'ready'; data: TimelineFile };

export const Timeline = () => {
  const t = useT();
  const [state, setState] = useState<LoadState>({ status: 'loading' });
  const [stepIndex, setStepIndex] = useState(0);
  const [playing, setPlaying] = useState(false);

  useEffect(() => {
    let cancelled = false;
    fetch('/data/timeline.json')
      .then((response) => {
        if (!response.ok) {
          throw new Error(String(response.status));
        }
        return response.json();
      })
      .then((data: TimelineFile) => {
        if (!cancelled) {
          setState(
            data.steps.length > 0 ? { status: 'ready', data } : { status: 'error' }
          );
        }
      })
      .catch(() => {
        if (!cancelled) {
          setState({ status: 'error' });
        }
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const stepCount = state.status === 'ready' ? state.data.steps.length : 0;

  useEffect(() => {
    if (!playing || stepCount === 0) {
      return;
    }
    const id = window.setInterval(() => {
      setStepIndex((current) => Math.min(current + 1, stepCount - 1));
    }, PLAY_INTERVAL_MS);
    return () => window.clearInterval(id);
  }, [playing, stepCount]);

  useEffect(() => {
    if (playing && stepCount > 0 && stepIndex >= stepCount - 1) {
      setPlaying(false);
    }
  }, [playing, stepIndex, stepCount]);

  if (state.status === 'loading') {
    return <p className="timeline-status">{t('steps.loading')}</p>;
  }
  if (state.status === 'error') {
    return <p className="timeline-status timeline-error">{t('steps.error')}</p>;
  }

  const steps = state.data.steps;
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
      <WellsTable wells={step.wells} />
    </section>
  );
};
