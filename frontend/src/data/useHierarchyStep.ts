import type { HierarchyStep } from '../api/types';
import { useOptionalScenario } from '../state/ScenarioContext';
import type { ResourceState } from './ResourceState';
import { useJsonResource } from './useJsonResource';
import { isHierarchyStepFile } from './validators';

export const hierarchyStepFile = (template: string, step: number): string =>
  template.replaceAll('{step}', String(step));

export const useHierarchyStep = (
  template: string | null,
  step: number | null
): ResourceState<HierarchyStep> => {
  const { dataUrl } = useOptionalScenario();
  const url =
    template === null || step === null || step < 0
      ? null
      : dataUrl(hierarchyStepFile(template, step));
  return useJsonResource(url, isHierarchyStepFile);
};
