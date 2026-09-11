import { useCallback, useMemo, useReducer, useState } from 'react';
import { useI18n } from '@/shared/i18n/I18nContext';
import { useRoute } from '@/shared/router/RouterProvider';
import { usePlayback } from '@/entities/timeline/model/PlaybackContext';
import { useScenario } from '@/entities/scenarios/model/ScenarioContext';
import { useTimeline } from '@/entities/timeline/model/TimelineContext';
import { useConsoleActions } from '@/jarvis/actions/lib/useConsoleActions';
import type { JarvisSessionValue } from '@/jarvis/model/jarvisValue';
import {
  CLOSED,
  isMoving,
  isVisible,
  transitionReducer,
  type TransitionPhase
} from '@/jarvis/model/transition';
import { useJarvisBriefing } from '@/jarvis/provider/useJarvisBriefing';
import { useJarvisHealth } from '@/jarvis/provider/useJarvisHealth';
import { useJarvisHistory } from '@/jarvis/provider/useJarvisHistory';
import { useJarvisHotkey } from '@/jarvis/provider/useJarvisHotkey';
import { useJarvisSession } from '@/jarvis/provider/useJarvisSession';
import { useTransitionEffects } from '@/jarvis/provider/useTransitionEffects';
import { createTransport } from '@/jarvis/transport/createTransport';
import type { JarvisAskContext } from '@/jarvis/transport/events';
import type { JarvisTransport } from '@/jarvis/transport/JarvisTransport';

const readReducedMotion = (): boolean =>
  typeof window !== 'undefined' &&
  typeof window.matchMedia === 'function' &&
  window.matchMedia('(prefers-reduced-motion: reduce)').matches;

export const useSessionValue = (transport?: JarvisTransport): JarvisSessionValue => {
  const { lang } = useI18n();
  const { workspace, view } = useRoute();
  const { activeId } = useScenario();
  const { timeline, stepIndex, selectedWell } = useTimeline();
  const { playing, togglePlay } = usePlayback();
  const [transition, dispatchTransition] = useReducer(transitionReducer, CLOSED);
  const [crossfade, setCrossfade] = useState(readReducedMotion);

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
  const { capabilities, probe } = useJarvisHealth(isVisible(transition), sceneError !== null);
  const { askQuestion } = session;
  const retry = useCallback(() => {
    probe();
    if (current !== undefined && current.question.length > 0) {
      askQuestion(current.question);
    }
  }, [probe, askQuestion, current]);
  const applyAction = useConsoleActions();

  return useMemo<JarvisSessionValue>(
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
      askContext,
      transportMode: active.mode,
      capabilities,
      retry,
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
      askContext,
      active.mode,
      capabilities,
      retry,
      applyAction
    ]
  );
};
