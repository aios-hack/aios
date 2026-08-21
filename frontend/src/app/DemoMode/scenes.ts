import type { Workspace, WorkspaceView } from '../../state/ConsoleContext';

export const SCENE_MODES = ['projection', 'chrono', 'wall', 'council'] as const;

export type SceneMode = (typeof SCENE_MODES)[number];

export const DOC_SCENE_MODES: Record<string, SceneMode> = {
  projection: 'projection',
  chronomap: 'chrono',
  chrono: 'chrono',
  wall: 'wall',
  council: 'council'
};

export const sceneModeOf = (documentScene: string): SceneMode | null => {
  const mode = DOC_SCENE_MODES[documentScene];
  return mode !== undefined && SCENE_MODES.includes(mode) ? mode : null;
};

const SCENE_WORKSPACE: Record<SceneMode, { workspace: Workspace; view: WorkspaceView }> = {
  projection: { workspace: 'field', view: 'projection' },
  chrono: { workspace: 'history', view: 'matrix' },
  wall: { workspace: 'history', view: 'wall' },
  council: { workspace: 'decisions', view: 'council' }
};

export const workspaceViewOfScene = (
  scene: SceneMode
): { workspace: Workspace; view: WorkspaceView } => SCENE_WORKSPACE[scene];
