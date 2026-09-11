export const WORKSPACES = ['overview', 'field', 'history', 'decisions', 'money'] as const;

export type Workspace = (typeof WORKSPACES)[number];

export const WORKSPACE_VIEWS = {
  overview: ['fund'],
  field: ['projection', 'maps'],
  history: ['matrix', 'wall', 'table'],
  decisions: ['council', 'rules'],
  money: ['rank', 'comparison', 'constraints']
} as const;

export type WorkspaceView<W extends Workspace = Workspace> =
  (typeof WORKSPACE_VIEWS)[W][number];

export const defaultViewOf = (workspace: Workspace): WorkspaceView =>
  WORKSPACE_VIEWS[workspace][0];

export const viewsOf = (workspace: Workspace): readonly WorkspaceView[] =>
  WORKSPACE_VIEWS[workspace];

export const isWorkspace = (value: string): value is Workspace =>
  (WORKSPACES as readonly string[]).includes(value);

export const isWorkspaceView = (workspace: Workspace, value: string): boolean =>
  (WORKSPACE_VIEWS[workspace] as readonly string[]).includes(value);
