import {
  createContext,
  useCallback,
  useContext,
  useMemo,
  useState,
  type ReactNode
} from 'react';
import {
  defaultViewOf,
  viewsOf,
  WORKSPACES,
  type Workspace,
  type WorkspaceView
} from '@/shared/router/routes';

interface RouteContextValue {
  workspaces: readonly Workspace[];
  workspace: Workspace;
  setWorkspace: (workspace: Workspace) => void;
  view: WorkspaceView;
  setView: (view: WorkspaceView) => void;
  setRoute: (workspace: Workspace, view: WorkspaceView) => void;
  viewsFor: (workspace: Workspace) => readonly WorkspaceView[];
}

const RouteContext = createContext<RouteContextValue | null>(null);

export const RouterProvider = ({ children }: { children: ReactNode }) => {
  const [workspace, setWorkspaceState] = useState<Workspace>('overview');
  const [view, setView] = useState<WorkspaceView>(defaultViewOf('overview'));

  const setWorkspace = useCallback((next: Workspace) => {
    setWorkspaceState(next);
    setView(defaultViewOf(next));
  }, []);

  const setRoute = useCallback((next: Workspace, nextView: WorkspaceView) => {
    setWorkspaceState(next);
    setView(nextView);
  }, []);

  const value = useMemo<RouteContextValue>(
    () => ({
      workspaces: WORKSPACES,
      workspace,
      setWorkspace,
      view,
      setView,
      setRoute,
      viewsFor: viewsOf
    }),
    [workspace, setWorkspace, view, setRoute]
  );

  return <RouteContext.Provider value={value}>{children}</RouteContext.Provider>;
};

export const useRoute = (): RouteContextValue => {
  const value = useContext(RouteContext);
  if (!value) {
    throw new Error('useRoute must be used within RouterProvider');
  }
  return value;
};
