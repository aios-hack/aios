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

export const PLAY_SPEED_MIN = 0.25;
export const PLAY_SPEED_MAX = 3;
export const PLAY_SPEED_STEP = 0.05;
export const PLAY_SPEED_DEFAULT = 1;

export type PlaySpeed = number;

export const clampSpeed = (speed: number): PlaySpeed =>
  Math.min(PLAY_SPEED_MAX, Math.max(PLAY_SPEED_MIN, Math.round(speed / PLAY_SPEED_STEP) * PLAY_SPEED_STEP));

export const playIntervalMs = (speed: PlaySpeed): number =>
  Math.max(1, Math.round(PLAY_INTERVAL_MS / speed));

interface PlaybackContextValue {
  playing: boolean;
  speed: PlaySpeed;
  speedMin: number;
  speedMax: number;
  speedStep: number;
  showDate: boolean;
  settingsOpen: boolean;
  axisCollapsed: boolean;
  setAxisCollapsed: (collapsed: boolean) => void;
  setSettingsOpen: (open: boolean) => void;
  setShowDate: (show: boolean) => void;
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
  const [speed, setSpeed] = useState<PlaySpeed>(PLAY_SPEED_DEFAULT);
  const [showDate, setShowDate] = useState(true);
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [axisCollapsed, setAxisCollapsed] = useState(false);
  const stepCountRef = useRef(stepCount);
  stepCountRef.current = stepCount;
  const currentRef = useRef(stepIndex);
  currentRef.current = stepIndex;

  useEffect(() => {
    if (!playing || stepCount === 0) {
      return;
    }
    const last = stepCount - 1;
    if (currentRef.current >= last) {
      setPlaying(false);
      return;
    }
    const id = window.setInterval(() => {
      if (currentRef.current >= last) {
        setPlaying(false);
        return;
      }
      setStepIndex((current) => Math.min(current + 1, last));
    }, playIntervalMs(speed));
    return () => window.clearInterval(id);
  }, [playing, speed, stepCount, setStepIndex]);

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
    () => ({
      playing,
      speed,
      speedMin: PLAY_SPEED_MIN,
      speedMax: PLAY_SPEED_MAX,
      speedStep: PLAY_SPEED_STEP,
      showDate,
      settingsOpen,
      axisCollapsed,
      setAxisCollapsed,
      setSettingsOpen,
      setShowDate,
      setSpeed,
      selectStep,
      onStep,
      togglePlay
    }),
    [playing, speed, showDate, settingsOpen, axisCollapsed, selectStep, onStep, togglePlay]
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
