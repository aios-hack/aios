import { scenarioDataUrl, useOptionalScenario } from '@/entities/scenarios/model/ScenarioContext';
import { DATASETS, type DatasetMap, type DatasetName } from '@/entities/registry';
import type { ResourceState } from '@/shared/api/ResourceState';
import { useJsonResource } from '@/shared/api/useJsonResource';

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
