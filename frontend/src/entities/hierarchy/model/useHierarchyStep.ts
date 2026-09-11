import type { HierarchyStep } from '@/entities/hierarchy/types';
import { useOptionalScenario } from '@/entities/scenarios/model/ScenarioContext';
import type { ResourceState } from '@/shared/api/ResourceState';
import { useJsonResource } from '@/shared/api/useJsonResource';
import { isHierarchyStepFile } from '@/entities/hierarchy/validate';

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
