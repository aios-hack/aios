import type { TimelineFile, WellRole } from '../../api/types';

export type { WellRole };

export const rolesAtStep = (
  timeline: TimelineFile | null,
  stepIndex: number
): Map<string, WellRole> => {
  const roles = new Map<string, WellRole>();
  if (timeline === null || timeline.steps.length === 0) {
    return roles;
  }
  const step = timeline.steps[Math.min(Math.max(stepIndex, 0), timeline.steps.length - 1)];
  if (step === undefined) {
    return roles;
  }
  for (const well of step.wells) {
    roles.set(well.well, well.role);
  }
  return roles;
};
