import { useDataset } from '../../data';
import { useTimeline } from '../../state/TimelineContext';
import { ConstraintsEditor } from './ConstraintsEditor';
import { ScenarioComparison } from './ScenarioComparison';
import { ScenarioLibrary } from './ScenarioLibrary';
import './ScenariosLibrary.css';

const FALLBACK_INTERVALS = 224;

export const Scenarios = () => {
  const { timeline } = useTimeline();
  const index = useDataset('scenarios');
  const nIntervals =
    timeline.status === 'ready' ? timeline.data.n_intervals : FALLBACK_INTERVALS;

  return (
    <div className="scenarios">
      {index.status === 'ready' && <ScenarioComparison entries={index.data.scenarios} />}
      <ScenarioLibrary />
      <ConstraintsEditor nIntervals={nIntervals} />
    </div>
  );
};
