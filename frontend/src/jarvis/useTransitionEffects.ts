import { useEffect, useRef } from 'react';
import {
  PHASE_GRACE_MS,
  isMoving,
  isVisible,
  phaseDurationMs,
  type TransitionPhase,
  type TransitionState
} from './transition';

interface EffectOptions {
  transition: TransitionState;
  settle: (phase: TransitionPhase) => void;
  playing: boolean;
  togglePlay: () => void;
  cancel: () => void;
}

export const useTransitionEffects = ({
  transition,
  settle,
  playing,
  togglePlay,
  cancel
}: EffectOptions): void => {
  const resume = useRef(false);

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
    resume.current = true;
    togglePlay();
  }, [transition, playing, togglePlay]);

  useEffect(() => {
    if (transition.phase !== 'closed' || !resume.current) {
      return;
    }
    resume.current = false;
    togglePlay();
  }, [transition.phase, togglePlay]);

  useEffect(() => {
    if (!isVisible(transition)) {
      cancel();
    }
  }, [transition, cancel]);
};
