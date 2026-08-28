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

export const parseRoute = (path: string): WorkspaceRoute | null => {
  const raw = path.replace(/^#?\/*/, '').replace(/\/+$/, '');
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
  `/${route.workspace}/${route.view}`;

interface RoutingOptions {
  workspace: Workspace;
  view: WorkspaceView;
  setRoute: (workspace: Workspace, view: WorkspaceView) => void;
}

export const useWorkspaceRouting = ({ workspace, view, setRoute }: RoutingOptions): void => {
  const apply = useRef({ setRoute });
  apply.current = { setRoute };
  const pending = useRef<WorkspaceRoute | null>(parseRoute(window.location.pathname));

  useEffect(() => {
    const fromPath = () => {
      const route = parseRoute(window.location.pathname);
      if (route === null) {
        return;
      }
      pending.current = route;
      apply.current.setRoute(route.workspace, route.view);
    };
    fromPath();
    window.addEventListener('popstate', fromPath);
    return () => window.removeEventListener('popstate', fromPath);
  }, []);

  useEffect(() => {
    const wanted = pending.current;
    if (wanted !== null) {
      if (wanted.workspace !== workspace || wanted.view !== view) {
        return;
      }
      pending.current = null;
    }
    const next = formatRoute({ workspace, view });
    if (window.location.pathname !== next) {
      window.history.pushState(null, '', next);
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
      const target = WORKSPACES[position - 1];
      apply.current.setRoute(target, WORKSPACE_VIEWS[target][0]);
    };
    window.addEventListener('keydown', onKeyDown);
    return () => window.removeEventListener('keydown', onKeyDown);
  }, []);
};
