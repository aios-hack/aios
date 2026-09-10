import {
  createContext,
  useCallback,
  useContext,
  useMemo,
  useReducer,
  useState,
  type ReactNode
} from 'react';
import { useI18n } from '../i18n/I18nContext';
import { useConsole } from '../state/ConsoleContext';
import { usePlayback } from '../state/PlaybackContext';
import { useScenario } from '../state/ScenarioContext';
import { useTimeline } from '../state/TimelineContext';
import { useConsoleActions } from './actions/useConsoleActions';
import type { SphereState } from './sphere/sphereState';
import type { JarvisTransport } from './transport/JarvisTransport';
import type { JarvisAskContext } from './transport/events';
import { createTransport } from './transport/createTransport';
import { useJarvisHealth } from './useJarvisHealth';
import { useJarvisHistory } from './useJarvisHistory';
import { useJarvisHotkey } from './useJarvisHotkey';
import { useJarvisSession } from './useJarvisSession';
import { useJarvisBriefing } from './useJarvisBriefing';
import { useTransitionEffects } from './useTransitionEffects';
import type { JarvisContextValue } from './jarvisValue';
import {
  CONFIRM_KEY,
  EMPTY_TRANSCRIPT,
  SPEAK_KEY,
  readFlag,
  writeFlag,
  type Transcript
} from './prefs';
import {
  CLOSED,
  isMoving,
  isVisible,
  transitionReducer,
  type TransitionPhase
} from './transition';

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
  const [transcript, setTranscript] = useState<Transcript>(EMPTY_TRANSCRIPT);
  const [sttError, setSttError] = useState<string | null>(null);
  const [confirmVoice, setConfirmVoice] = useState(() => readFlag(CONFIRM_KEY, false));
  const [voiceAsked, setVoiceAsked] = useState(false);
  const [crossfade, setCrossfade] = useState(readReducedMotion);
  const [speakEnabled, setSpeakEnabled] = useState(() => readFlag(SPEAK_KEY, false));

  const active = useMemo(() => transport ?? createTransport(), [transport]);

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
  const { cancel, pushEvents, sessionId } = session;
  const sceneCount = session.scenes.scenes.length;

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

  useTransitionEffects({ transition, settle, playing, togglePlay, cancel });

  useJarvisBriefing({
    open: transition.phase === 'open',
    sessionId,
    sceneCount,
    lang,
    scenario: askContext.scenario,
    step: askContext.step,
    pushEvents
  });

  const current = session.scenes.scenes[session.scenes.activeIndex];
  const sceneError = current?.error ?? null;
  const status = session.scenes.status;
  const { capabilities, probe } = useJarvisHealth(
    isVisible(transition),
    sceneError !== null
  );
  const { askQuestion } = session;
  const retry = useCallback(() => {
    probe();
    if (current !== undefined && current.question.length > 0) {
      askQuestion(current.question);
    }
  }, [probe, askQuestion, current]);
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

  const toggleSpeak = useCallback(
    () =>
      setSpeakEnabled((value) => {
        writeFlag(SPEAK_KEY, !value);
        return !value;
      }),
    []
  );
  const toggleConfirmVoice = useCallback(
    () =>
      setConfirmVoice((value) => {
        writeFlag(CONFIRM_KEY, !value);
        return !value;
      }),
    []
  );
  const noteVoiceAsked = useCallback(() => setVoiceAsked(true), []);
  const clearVoiceAsked = useCallback(() => setVoiceAsked(false), []);
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
      transcript,
      setTranscript,
      sttError,
      setSttError,
      confirmVoice,
      toggleConfirmVoice,
      voiceAsked,
      noteVoiceAsked,
      clearVoiceAsked,
      askContext,
      transportMode: active.mode,
      capabilities,
      retry,
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
      transcript,
      sttError,
      confirmVoice,
      toggleConfirmVoice,
      voiceAsked,
      noteVoiceAsked,
      clearVoiceAsked,
      askContext,
      active.mode,
      capabilities,
      retry,
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
