import {
  WORKSPACES,
  WORKSPACE_VIEWS,
  type Workspace,
  type WorkspaceView
} from '../../state/ConsoleContext';

export interface ConsoleAction {
  workspace?: Workspace;
  view?: WorkspaceView;
  scenario?: string;
  step?: number;
  well?: string | null;
  play?: boolean;
  spotlight?: string;
}

export const isWorkspace = (value: unknown): value is Workspace =>
  typeof value === 'string' && (WORKSPACES as readonly string[]).includes(value);

export const isView = (value: unknown, workspace: Workspace): value is WorkspaceView =>
  typeof value === 'string' &&
  (WORKSPACE_VIEWS[workspace] as readonly string[]).includes(value);

export const routeAction = (
  workspace: string,
  view: string,
  spotlight: string | null
): ConsoleAction => {
  const action: ConsoleAction = {};
  if (isWorkspace(workspace)) {
    action.workspace = workspace;
    if (isView(view, workspace)) {
      action.view = view;
    }
  }
  if (spotlight !== null) {
    action.spotlight = spotlight;
  }
  return action;
};
