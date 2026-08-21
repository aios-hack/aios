import { useDataset } from '../../data';
import { ScenarioComparison } from '../Scenarios/ScenarioComparison';
import { ScenarioLibrary } from '../Scenarios/ScenarioLibrary';

export const MoneyComparison = () => {
  const index = useDataset('scenarios');

  return (
    <div className="money-comparison">
      {index.status === 'ready' && <ScenarioComparison entries={index.data.scenarios} />}
      <ScenarioLibrary />
    </div>
  );
};
