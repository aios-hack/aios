import { useEffect, useRef } from 'react';
import {
  WORKSPACES,
  WORKSPACE_VIEWS,
  type Workspace,
  type WorkspaceView
} from '../state/ConsoleContext';
import { isEditableTarget } from './useHotkeys';

export interface WorkspaceRoute {
  workspace: Workspace;
  view: WorkspaceView;
}

export const parseRoute = (hash: string): WorkspaceRoute | null => {
  const raw = hash.replace(/^#\/?/, '');
  if (raw.length === 0) {
    return null;
  }
  const [workspacePart, viewPart] = raw.split('/');
  const workspace = WORKSPACES.find((id) => id === workspacePart);
  if (workspace === undefined) {
    return null;
  }
  const views: readonly string[] = WORKSPACE_VIEWS[workspace];
  const view = views.find((id) => id === viewPart);
  return {
    workspace,
    view: (view ?? views[0]) as WorkspaceView
  };
};

export const formatRoute = (route: WorkspaceRoute): string =>
  `#/${route.workspace}/${route.view}`;

interface RoutingOptions {
  workspace: Workspace;
  view: WorkspaceView;
  setWorkspace: (workspace: Workspace) => void;
  setView: (view: WorkspaceView) => void;
}

export const useWorkspaceRouting = ({
  workspace,
  view,
  setWorkspace,
  setView
}: RoutingOptions): void => {
  const apply = useRef({ setWorkspace, setView });
  apply.current = { setWorkspace, setView };

  useEffect(() => {
    const fromHash = () => {
      const route = parseRoute(window.location.hash);
      if (route === null) {
        return;
      }
      apply.current.setWorkspace(route.workspace);
      apply.current.setView(route.view);
    };
    fromHash();
    window.addEventListener('hashchange', fromHash);
    return () => window.removeEventListener('hashchange', fromHash);
  }, []);

  useEffect(() => {
    const next = formatRoute({ workspace, view });
    if (window.location.hash !== next) {
      window.history.replaceState(null, '', next);
    }
  }, [workspace, view]);

  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.defaultPrevented || event.metaKey || event.ctrlKey || event.altKey) {
        return;
      }
      if (isEditableTarget(event.target)) {
        return;
      }
      const position = Number(event.key);
      if (!Number.isInteger(position) || position < 1 || position > WORKSPACES.length) {
        return;
      }
      event.preventDefault();
      apply.current.setWorkspace(WORKSPACES[position - 1]);
    };
    window.addEventListener('keydown', onKeyDown);
    return () => window.removeEventListener('keydown', onKeyDown);
  }, []);
};
