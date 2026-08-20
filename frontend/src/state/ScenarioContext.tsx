import {
  createContext,
  useCallback,
  useContext,
  useMemo,
  useState,
  type ReactNode
} from 'react';

export const DEFAULT_SCENARIO_ID = '';

interface ScenarioContextValue {
  activeId: string;
  selectScenario: (id: string) => void;
  dataUrl: (file: string) => string;
}

const ScenarioContext = createContext<ScenarioContextValue | null>(null);

const SAFE_SCENARIO_ID = /^[A-Za-z0-9_-]{1,64}$/;

export const isSafeScenarioId = (id: string): boolean => SAFE_SCENARIO_ID.test(id);

export const scenarioDataUrl = (activeId: string, file: string): string =>
  activeId === DEFAULT_SCENARIO_ID || !isSafeScenarioId(activeId)
    ? `/data/${file}`
    : `/data/${activeId}/${file}`;

export const ScenarioProvider = ({
  children,
  initialId = DEFAULT_SCENARIO_ID
}: {
  children: ReactNode;
  initialId?: string;
}) => {
  const [activeId, setActiveId] = useState(initialId);
  const selectScenario = useCallback(
    (id: string) => setActiveId(isSafeScenarioId(id) ? id : DEFAULT_SCENARIO_ID),
    []
  );
  const dataUrl = useCallback((file: string) => scenarioDataUrl(activeId, file), [activeId]);
  const value = useMemo(
    () => ({ activeId, selectScenario, dataUrl }),
    [activeId, selectScenario, dataUrl]
  );

  return <ScenarioContext.Provider value={value}>{children}</ScenarioContext.Provider>;
};

export const useScenario = (): ScenarioContextValue => {
  const value = useContext(ScenarioContext);
  if (!value) {
    throw new Error('useScenario must be used within ScenarioProvider');
  }
  return value;
};

const DETACHED: ScenarioContextValue = {
  activeId: DEFAULT_SCENARIO_ID,
  selectScenario: () => undefined,
  dataUrl: (file) => scenarioDataUrl(DEFAULT_SCENARIO_ID, file)
};

export const useOptionalScenario = (): ScenarioContextValue =>
  useContext(ScenarioContext) ?? DETACHED;
