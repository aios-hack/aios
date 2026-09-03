import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useReducer,
  useRef,
  useState,
  type ReactNode
} from 'react';
import { useI18n } from '../i18n/I18nContext';
import { useConsole } from '../state/ConsoleContext';
import { usePlayback } from '../state/PlaybackContext';
import { useScenario } from '../state/ScenarioContext';
import { useTimeline } from '../state/TimelineContext';
import { useConsoleActions } from './actions/useConsoleActions';
import type { ConsoleAction } from './actions/consoleAction';
import type { SphereState } from './sphere/sphereState';
import type { JarvisTransport } from './transport/JarvisTransport';
import type { JarvisAskContext } from './transport/events';
import { createTransport, type TransportMode } from './transport/createTransport';
import { useJarvisHistory } from './useJarvisHistory';
import { useJarvisHotkey } from './useJarvisHotkey';
import { useJarvisSession, type JarvisSession } from './useJarvisSession';
import {
  CLOSED,
  PHASE_GRACE_MS,
  isMoving,
  isVisible,
  phaseDurationMs,
  transitionReducer,
  type TransitionPhase,
  type TransitionState
} from './transition';

interface JarvisContextValue extends JarvisSession {
  transition: TransitionState;
  visible: boolean;
  moving: boolean;
  open: () => void;
  close: () => void;
  settle: (phase: TransitionPhase) => void;
  crossfade: boolean;
  requestCrossfade: () => void;
  sphereState: SphereState;
  setHovering: (hovering: boolean) => void;
  audioLevel: number;
  setAudioLevel: (level: number) => void;
  micOpen: boolean;
  setMicOpen: (open: boolean) => void;
  askContext: JarvisAskContext;
  transportMode: TransportMode;
  degraded: boolean;
  speakEnabled: boolean;
  toggleSpeak: () => void;
  applyAction: (action: ConsoleAction) => void;
}

const JarvisContext = createContext<JarvisContextValue | null>(null);

const readReducedMotion = (): boolean =>
  typeof window !== 'undefined' &&
  typeof window.matchMedia === 'function' &&
  window.matchMedia('(prefers-reduced-motion: reduce)').matches;

export const JarvisProvider = ({
  children,
  transport
}: {
  children: ReactNode;
  transport?: JarvisTransport;
}) => {
  const { lang } = useI18n();
  const { workspace, view } = useConsole();
  const { activeId } = useScenario();
  const { timeline, stepIndex, selectedWell } = useTimeline();
  const { playing, togglePlay } = usePlayback();
  const [transition, dispatchTransition] = useReducer(transitionReducer, CLOSED);
  const [hovering, setHovering] = useState(false);
  const [audioLevel, setAudioLevel] = useState(0);
  const [micOpen, setMicOpen] = useState(false);
  const [crossfade, setCrossfade] = useState(readReducedMotion);
  const [speakEnabled, setSpeakEnabled] = useState(false);
  const [degraded, setDegraded] = useState(false);
  const resumeRef = useRef(false);

  const onDegrade = useCallback(() => setDegraded(true), []);
  const active = useMemo(
    () => transport ?? createTransport({ onDegrade }),
    [transport, onDegrade]
  );

  const steps = timeline.status === 'ready' ? timeline.data.steps : [];
  const date = steps[stepIndex]?.date ?? '';
  const askContext = useMemo<JarvisAskContext>(
    () => ({
      scenario: activeId === '' ? 'base' : activeId,
      step: stepIndex,
      date,
      selected_well: selectedWell,
      workspace,
      view
    }),
    [activeId, stepIndex, date, selectedWell, workspace, view]
  );

  const session = useJarvisSession(active, lang, askContext);
  const { cancel } = session;

  const open = useCallback(() => dispatchTransition({ kind: 'open' }), []);
  const close = useCallback(() => dispatchTransition({ kind: 'close' }), []);
  const settle = useCallback(
    (phase: TransitionPhase) => dispatchTransition({ kind: 'settled', phase }),
    []
  );
  const requestCrossfade = useCallback(() => setCrossfade(true), []);
  const onPop = useCallback(
    (flagged: boolean) => dispatchTransition({ kind: flagged ? 'open' : 'close' }),
    []
  );

  useJarvisHistory(transition, onPop);
  useJarvisHotkey(transition.phase === 'closed', open);

  useEffect(() => {
    if (!isMoving(transition)) {
      return;
    }
    const id = window.setTimeout(
      () => settle(transition.phase),
      phaseDurationMs(transition.phase) + PHASE_GRACE_MS
    );
    return () => window.clearTimeout(id);
  }, [transition, settle]);

  useEffect(() => {
    if (transition.phase !== 'shrinking' || transition.direction !== 'opening' || !playing) {
      return;
    }
    resumeRef.current = true;
    togglePlay();
  }, [transition, playing, togglePlay]);

  useEffect(() => {
    if (transition.phase !== 'closed' || !resumeRef.current) {
      return;
    }
    resumeRef.current = false;
    togglePlay();
  }, [transition.phase, togglePlay]);

  useEffect(() => {
    if (!isVisible(transition)) {
      cancel();
    }
  }, [transition, cancel]);

  const current = session.scenes.scenes[session.scenes.activeIndex];
  const sceneError = current?.error ?? null;
  const status = session.scenes.status;
  const sphereState = useMemo<SphereState>(() => {
    if (sceneError !== null) {
      return 'error';
    }
    if (micOpen) {
      return 'listening';
    }
    if (status === 'thinking' || status === 'tool') {
      return 'thinking';
    }
    if (status === 'composing') {
      return 'speaking';
    }
    return hovering ? 'hover' : 'idle';
  }, [sceneError, status, micOpen, hovering]);

  const toggleSpeak = useCallback(() => setSpeakEnabled((value) => !value), []);
  const applyAction = useConsoleActions();

  const value = useMemo<JarvisContextValue>(
    () => ({
      ...session,
      transition,
      visible: isVisible(transition),
      moving: isMoving(transition),
      open,
      close,
      settle,
      crossfade,
      requestCrossfade,
      sphereState,
      setHovering,
      audioLevel,
      setAudioLevel,
      micOpen,
      setMicOpen,
      askContext,
      transportMode: active.mode,
      degraded,
      speakEnabled,
      toggleSpeak,
      applyAction
    }),
    [
      session,
      transition,
      open,
      close,
      settle,
      crossfade,
      requestCrossfade,
      sphereState,
      audioLevel,
      micOpen,
      askContext,
      active.mode,
      degraded,
      speakEnabled,
      toggleSpeak,
      applyAction
    ]
  );

  return <JarvisContext.Provider value={value}>{children}</JarvisContext.Provider>;
};

export const useJarvis = (): JarvisContextValue => {
  const value = useContext(JarvisContext);
  if (value === null) {
    throw new Error('useJarvis must be used within JarvisProvider');
  }
  return value;
};

export const useOptionalJarvis = (): JarvisContextValue | null => useContext(JarvisContext);
