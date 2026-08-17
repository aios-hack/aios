import { scenarioDataUrl, useOptionalScenario } from '../state/ScenarioContext';
import { DATASETS, type DatasetMap, type DatasetName } from './datasets';
import type { ResourceState } from './ResourceState';
import { useJsonResource } from './useJsonResource';

export const useDataset = <K extends DatasetName>(
  name: K
): ResourceState<DatasetMap[K]> => {
  const { dataUrl } = useOptionalScenario();
  const spec = DATASETS[name];
  const url = spec.scope === 'scenario' ? dataUrl(spec.file) : `/data/${spec.file}`;
  return useJsonResource(url, spec.validate);
};

export const useScenarioDataset = <K extends DatasetName>(
  name: K,
  scenarioId: string | null
): ResourceState<DatasetMap[K]> => {
  const spec = DATASETS[name];
  const url =
    scenarioId === null ? null : scenarioDataUrl(scenarioId, spec.file);
  return useJsonResource(url, spec.validate);
};
