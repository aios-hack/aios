import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useState,
  type Dispatch,
  type ReactNode,
  type SetStateAction
} from 'react';
import type { TimelineFile, TraceFile } from '../api/types';
import { useOptionalScenario } from './ScenarioContext';

export type ResourceState<T> =
  | { status: 'loading' }
  | { status: 'error' }
  | { status: 'ready'; data: T };

interface TimelineContextValue {
  timeline: ResourceState<TimelineFile>;
  trace: ResourceState<TraceFile>;
  stepIndex: number;
  setStepIndex: Dispatch<SetStateAction<number>>;
  selectedWell: string | null;
  selectWell: (well: string | null) => void;
}

const TimelineContext = createContext<TimelineContextValue | null>(null);

const isTimelineFile = (data: unknown): data is TimelineFile =>
  typeof data === 'object' &&
  data !== null &&
  Array.isArray((data as { steps?: unknown }).steps) &&
  (data as { steps: unknown[] }).steps.length > 0;

const isTraceFile = (data: unknown): data is TraceFile =>
  typeof data === 'object' && data !== null && !Array.isArray(data);

export const useJsonResource = <T,>(
  url: string,
  validate: (data: unknown) => data is T
): ResourceState<T> => {
  const [state, setState] = useState<ResourceState<T>>({ status: 'loading' });

  useEffect(() => {
    let cancelled = false;
    fetch(url)
      .then((response) => {
        if (!response.ok) {
          throw new Error(String(response.status));
        }
        return response.json();
      })
      .then((data: unknown) => {
        if (!cancelled) {
          setState(validate(data) ? { status: 'ready', data } : { status: 'error' });
        }
      })
      .catch(() => {
        if (!cancelled) {
          setState({ status: 'error' });
        }
      });
    return () => {
      cancelled = true;
    };
  }, [url]);

  return state;
};

export const TimelineProvider = ({ children }: { children: ReactNode }) => {
  const { activeId, dataUrl } = useOptionalScenario();
  const timeline = useJsonResource(dataUrl('timeline.json'), isTimelineFile);
  const trace = useJsonResource(dataUrl('trace.json'), isTraceFile);
  const [stepIndex, setStepIndex] = useState(0);
  const [selectedWell, setSelectedWell] = useState<string | null>(null);
  const selectWell = useCallback((well: string | null) => setSelectedWell(well), []);

  useEffect(() => {
    setStepIndex(0);
    setSelectedWell(null);
  }, [activeId]);

  return (
    <TimelineContext.Provider
      value={{ timeline, trace, stepIndex, setStepIndex, selectedWell, selectWell }}
    >
      {children}
    </TimelineContext.Provider>
  );
};

export const useTimeline = (): TimelineContextValue => {
  const value = useContext(TimelineContext);
  if (!value) {
    throw new Error('useTimeline must be used within TimelineProvider');
  }
  return value;
};
