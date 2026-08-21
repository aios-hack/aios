import { useTimeline } from '../state/TimelineContext';
import { FieldStats } from '../views/Timeline/FieldStats';

export const FieldStrip = () => {
  const { timeline, stepIndex } = useTimeline();

  if (timeline.status !== 'ready' || timeline.data.steps.length === 0) {
    return null;
  }

  const steps = timeline.data.steps;
  const current = Math.min(stepIndex, steps.length - 1);

  return (
    <div className="console-strip" data-testid="console-strip">
      <FieldStats steps={steps} stepIndex={current} norms={timeline.data.field_norms} />
    </div>
  );
};
