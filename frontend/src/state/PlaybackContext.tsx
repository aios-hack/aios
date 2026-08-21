import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode
} from 'react';
import { useTimeline } from './TimelineContext';

export const PLAY_INTERVAL_MS = 300;

export const PLAY_SPEEDS = [1, 4, 16] as const;

export type PlaySpeed = (typeof PLAY_SPEEDS)[number];

export const playIntervalMs = (speed: PlaySpeed): number =>
  Math.max(1, Math.round(PLAY_INTERVAL_MS / speed));

interface PlaybackContextValue {
  playing: boolean;
  speed: PlaySpeed;
  setSpeed: (speed: PlaySpeed) => void;
  selectStep: (index: number) => void;
  onStep: (delta: number) => void;
  togglePlay: () => void;
}

const PlaybackContext = createContext<PlaybackContextValue | null>(null);

export const PlaybackProvider = ({ children }: { children: ReactNode }) => {
  const { timeline, stepIndex, setStepIndex } = useTimeline();
  const stepCount = timeline.status === 'ready' ? timeline.data.steps.length : 0;
  const [playing, setPlaying] = useState(false);
  const [speed, setSpeed] = useState<PlaySpeed>(PLAY_SPEEDS[0]);
  const stepCountRef = useRef(stepCount);
  stepCountRef.current = stepCount;
  const currentRef = useRef(stepIndex);
  currentRef.current = stepIndex;

  useEffect(() => {
    if (!playing || stepCount === 0) {
      return;
    }
    const id = window.setInterval(() => {
      setStepIndex((current) => Math.min(current + 1, stepCount - 1));
    }, playIntervalMs(speed));
    return () => window.clearInterval(id);
  }, [playing, speed, stepCount, setStepIndex]);

  useEffect(() => {
    if (playing && stepCount > 0 && stepIndex >= stepCount - 1) {
      setPlaying(false);
    }
  }, [playing, stepIndex, stepCount]);

  const selectStep = useCallback(
    (index: number) => {
      setPlaying(false);
      const last = Math.max(stepCountRef.current - 1, 0);
      setStepIndex(Math.min(Math.max(index, 0), last));
    },
    [setStepIndex]
  );

  const onStep = useCallback(
    (delta: number) => selectStep(currentRef.current + delta),
    [selectStep]
  );

  const togglePlay = useCallback(() => {
    if (currentRef.current >= stepCountRef.current - 1) {
      setStepIndex(0);
    }
    setPlaying((value) => !value);
  }, [setStepIndex]);

  const value = useMemo<PlaybackContextValue>(
    () => ({ playing, speed, setSpeed, selectStep, onStep, togglePlay }),
    [playing, speed, selectStep, onStep, togglePlay]
  );

  return <PlaybackContext.Provider value={value}>{children}</PlaybackContext.Provider>;
};

export const usePlayback = (): PlaybackContextValue => {
  const value = useContext(PlaybackContext);
  if (!value) {
    throw new Error('usePlayback must be used within PlaybackProvider');
  }
  return value;
};
