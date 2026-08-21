import {
  createContext,
  useCallback,
  useContext,
  useMemo,
  useState,
  type ReactNode
} from 'react';

export const WORKSPACES = ['field', 'history', 'decisions', 'money'] as const;

export type Workspace = (typeof WORKSPACES)[number];

export const WORKSPACE_VIEWS = {
  field: ['projection'],
  history: ['matrix', 'wall', 'table'],
  decisions: ['council', 'rules'],
  money: ['rank', 'comparison', 'constraints']
} as const;

export type WorkspaceView<W extends Workspace = Workspace> =
  (typeof WORKSPACE_VIEWS)[W][number];

export interface MorphRequest {
  value: number;
  serial: number;
}

interface ConsoleContextValue {
  workspaces: readonly Workspace[];
  workspace: Workspace;
  setWorkspace: (workspace: Workspace) => void;
  view: WorkspaceView;
  setView: (view: WorkspaceView) => void;
  viewsFor: (workspace: Workspace) => readonly WorkspaceView[];
  morphRequest: MorphRequest | null;
  requestMorph: (value: number) => void;
}

const ConsoleContext = createContext<ConsoleContextValue | null>(null);

const defaultViewOf = (workspace: Workspace): WorkspaceView => WORKSPACE_VIEWS[workspace][0];

export const ConsoleProvider = ({ children }: { children: ReactNode }) => {
  const [workspace, setWorkspaceState] = useState<Workspace>('field');
  const [view, setView] = useState<WorkspaceView>(defaultViewOf('field'));
  const [morphRequest, setMorphRequest] = useState<MorphRequest | null>(null);

  const setWorkspace = useCallback((next: Workspace) => {
    setWorkspaceState(next);
    setView(defaultViewOf(next));
  }, []);

  const viewsFor = useCallback(
    (target: Workspace): readonly WorkspaceView[] => WORKSPACE_VIEWS[target],
    []
  );

  const requestMorph = useCallback(
    (value: number) =>
      setMorphRequest((current) => ({
        value: Math.min(Math.max(value, 0), 1),
        serial: (current?.serial ?? 0) + 1
      })),
    []
  );

  const value = useMemo<ConsoleContextValue>(
    () => ({
      workspaces: WORKSPACES,
      workspace,
      setWorkspace,
      view,
      setView,
      viewsFor,
      morphRequest,
      requestMorph
    }),
    [workspace, setWorkspace, view, viewsFor, morphRequest, requestMorph]
  );

  return <ConsoleContext.Provider value={value}>{children}</ConsoleContext.Provider>;
};

export const useMorphRequest = (): MorphRequest | null =>
  useContext(ConsoleContext)?.morphRequest ?? null;

export const useConsole = (): ConsoleContextValue => {
  const value = useContext(ConsoleContext);
  if (!value) {
    throw new Error('useConsole must be used within ConsoleProvider');
  }
  return value;
};
