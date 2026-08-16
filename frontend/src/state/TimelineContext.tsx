import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type Dispatch,
  type ReactNode,
  type SetStateAction
} from 'react';
import type { TimelineFile, TraceFile } from '../api/types';
import { useDataset, type ResourceState } from '../data';
import { useOptionalScenario } from './ScenarioContext';

export type { ResourceState };
export { useJsonResource } from '../data';

interface TimelineContextValue {
  timeline: ResourceState<TimelineFile>;
  trace: ResourceState<TraceFile>;
  stepIndex: number;
  setStepIndex: Dispatch<SetStateAction<number>>;
  selectedWell: string | null;
  selectWell: (well: string | null) => void;
}

const TimelineContext = createContext<TimelineContextValue | null>(null);

export const TimelineProvider = ({ children }: { children: ReactNode }) => {
  const { activeId } = useOptionalScenario();
  const timeline = useDataset('timeline');
  const trace = useDataset('trace');
  const [rawStepIndex, setStepIndex] = useState(0);
  const [selectedWell, setSelectedWell] = useState<string | null>(null);
  const selectWell = useCallback((well: string | null) => setSelectedWell(well), []);

  useEffect(() => {
    setStepIndex(0);
    setSelectedWell(null);
  }, [activeId]);

  const stepCount = timeline.status === 'ready' ? timeline.data.steps.length : 0;
  const stepIndex =
    stepCount === 0 ? rawStepIndex : Math.min(Math.max(rawStepIndex, 0), stepCount - 1);

  const value = useMemo<TimelineContextValue>(
    () => ({ timeline, trace, stepIndex, setStepIndex, selectedWell, selectWell }),
    [timeline, trace, stepIndex, selectedWell, selectWell]
  );

  return <TimelineContext.Provider value={value}>{children}</TimelineContext.Provider>;
};

export const useTimeline = (): TimelineContextValue => {
  const value = useContext(TimelineContext);
  if (!value) {
    throw new Error('useTimeline must be used within TimelineProvider');
  }
  return value;
};
