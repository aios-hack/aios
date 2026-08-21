import type { ScenarioEntry, TimelineStep } from '../../api/types';
import { compareWellIds } from '../format/wellOrder';

export type CommandKind = 'well' | 'step' | 'scenario' | 'action';

export interface Command {
  id: string;
  kind: CommandKind;
  label: string;
  hint: string;
  value: string;
  index: number;
}

const DATE_QUERY = /^(\d{4})(?:[-/.](\d{1,2}))?$/;

const normalize = (value: string): string => value.trim().toLowerCase();

export const matches = (haystack: string, needle: string): boolean =>
  needle.length === 0 || normalize(haystack).includes(normalize(needle));

export const wellCommands = (wells: string[]): Command[] =>
  [...wells].sort(compareWellIds).map((well, index) => ({
    id: `well:${well}`,
    kind: 'well' as const,
    label: well,
    hint: '',
    value: well,
    index
  }));

export const scenarioCommands = (scenarios: ScenarioEntry[]): Command[] =>
  scenarios.map((scenario, index) => ({
    id: `scenario:${scenario.id}`,
    kind: 'scenario' as const,
    label: scenario.id,
    hint: '',
    value: scenario.id,
    index
  }));

export const nearestStepByDate = (
  steps: TimelineStep[],
  query: string
): number | null => {
  const parsed = DATE_QUERY.exec(query.trim());
  if (parsed === null || steps.length === 0) {
    return null;
  }
  const year = Number(parsed[1]);
  const month = parsed[2] === undefined ? null : Number(parsed[2]);
  if (month !== null && (month < 1 || month > 12)) {
    return null;
  }
  const target = year * 12 + (month === null ? 1 : month) - 1;
  let best = -1;
  let bestDistance = Number.POSITIVE_INFINITY;
  for (let index = 0; index < steps.length; index += 1) {
    const date = steps[index].date;
    const stepYear = Number(date.slice(0, 4));
    const stepMonth = Number(date.slice(5, 7));
    if (!Number.isFinite(stepYear) || !Number.isFinite(stepMonth)) {
      continue;
    }
    const distance = Math.abs(stepYear * 12 + stepMonth - 1 - target);
    if (distance < bestDistance) {
      bestDistance = distance;
      best = index;
    }
  }
  return best < 0 ? null : best;
};

export interface ActionEntry {
  id: string;
  label: string;
}

export const actionCommands = (actions: ActionEntry[]): Command[] =>
  actions.map((action, index) => ({
    id: `action:${action.id}`,
    kind: 'action' as const,
    label: action.label,
    hint: '',
    value: action.id,
    index
  }));

interface CommandSources {
  wells: string[];
  steps: TimelineStep[];
  scenarios: ScenarioEntry[];
  actions: ActionEntry[];
  query: string;
  stepLabel: (step: TimelineStep, index: number) => string;
}

export const buildCommands = ({
  wells,
  steps,
  scenarios,
  actions,
  query,
  stepLabel
}: CommandSources): Command[] => {
  const step = nearestStepByDate(steps, query);
  const stepEntries: Command[] =
    step === null
      ? []
      : [
          {
            id: `step:${step}`,
            kind: 'step',
            label: stepLabel(steps[step], step),
            hint: '',
            value: String(step),
            index: step
          }
        ];
  const wells_ = wellCommands(wells).filter((command) => matches(command.label, query));
  const scenarios_ = scenarioCommands(scenarios).filter((command) =>
    matches(command.label, query)
  );
  const actions_ = actionCommands(actions).filter((command) =>
    matches(command.label, query)
  );
  return [...actions_, ...stepEntries, ...wells_, ...scenarios_];
};
