import type { Workspace, WorkspaceView } from '../../state/ConsoleContext';
import { isView, isWorkspace, type ConsoleAction } from './consoleAction';

export interface ConsoleBridge {
  setRoute: (workspace: Workspace, view: WorkspaceView) => void;
  selectScenario: (id: string) => void;
  setStepIndex: (index: number) => void;
  selectWell: (well: string | null) => void;
  togglePlay: () => void;
  playing: boolean;
  stepCount: number;
  currentScenario: string;
  defaultViewOf: (workspace: Workspace) => WorkspaceView;
  spotlight: (anchor: string) => void;
}

export const APPLY_ORDER = [
  'scenario',
  'route',
  'step',
  'well',
  'play',
  'spotlight'
] as const;

export type ApplyStep = (typeof APPLY_ORDER)[number];

export const plannedSteps = (action: ConsoleAction): ApplyStep[] => {
  const steps: ApplyStep[] = [];
  if (action.scenario !== undefined) {
    steps.push('scenario');
  }
  if (action.workspace !== undefined) {
    steps.push('route');
  }
  if (action.step !== undefined) {
    steps.push('step');
  }
  if (action.well !== undefined) {
    steps.push('well');
  }
  if (action.play !== undefined) {
    steps.push('play');
  }
  if (action.spotlight !== undefined) {
    steps.push('spotlight');
  }
  return steps;
};

export const clampStep = (step: number, stepCount: number): number | null => {
  if (!Number.isFinite(step) || stepCount <= 0) {
    return null;
  }
  return Math.min(Math.max(Math.trunc(step), 0), stepCount - 1);
};

export const applyConsoleAction = (
  action: ConsoleAction,
  bridge: ConsoleBridge
): ApplyStep[] => {
  const applied: ApplyStep[] = [];

  if (action.scenario !== undefined && action.scenario !== bridge.currentScenario) {
    bridge.selectScenario(action.scenario);
    applied.push('scenario');
  }

  if (action.workspace !== undefined && isWorkspace(action.workspace)) {
    const view =
      action.view !== undefined && isView(action.view, action.workspace)
        ? action.view
        : bridge.defaultViewOf(action.workspace);
    bridge.setRoute(action.workspace, view);
    applied.push('route');
  }

  if (action.step !== undefined) {
    const step = clampStep(action.step, bridge.stepCount);
    if (step !== null) {
      bridge.setStepIndex(step);
      applied.push('step');
    }
  }

  if (action.well !== undefined) {
    bridge.selectWell(action.well);
    applied.push('well');
  }

  if (action.play !== undefined && action.play !== bridge.playing) {
    bridge.togglePlay();
    applied.push('play');
  }

  if (action.spotlight !== undefined) {
    bridge.spotlight(action.spotlight);
    applied.push('spotlight');
  }

  return applied;
};
