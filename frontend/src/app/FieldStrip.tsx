import { useConsole } from '../state/ConsoleContext';
import { useTimeline } from '../state/TimelineContext';
import { FieldStats } from '../views/Timeline/FieldStats';

const STRIP_WORKSPACES = new Set(['field', 'history']);

export const FieldStrip = () => {
  const { timeline, stepIndex } = useTimeline();
  const { workspace } = useConsole();

  if (!STRIP_WORKSPACES.has(workspace)) {
    return null;
  }

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
