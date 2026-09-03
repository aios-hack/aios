export const TRANSITION_PHASES = [
  'closed',
  'shrinking',
  'turning',
  'settling',
  'open'
] as const;

export type TransitionPhase = (typeof TRANSITION_PHASES)[number];

export type TransitionDirection = 'opening' | 'closing' | 'idle';

export interface TransitionState {
  phase: TransitionPhase;
  direction: TransitionDirection;
}

export type TransitionEvent =
  | { kind: 'open' }
  | { kind: 'close' }
  | { kind: 'settled'; phase: TransitionPhase }
  | { kind: 'abort' };

export const CLOSED: TransitionState = { phase: 'closed', direction: 'idle' };
export const OPEN: TransitionState = { phase: 'open', direction: 'idle' };

export const SHRINK_MS = 220;
export const TURN_MS = 600;
export const SETTLE_MS = 220;
export const CROSSFADE_MS = 200;
export const PHASE_GRACE_MS = 60;
export const TOTAL_MS = SHRINK_MS + TURN_MS + SETTLE_MS;

export const phaseDurationMs = (phase: TransitionPhase): number => {
  if (phase === 'shrinking') {
    return SHRINK_MS;
  }
  if (phase === 'turning') {
    return TURN_MS;
  }
  if (phase === 'settling') {
    return SETTLE_MS;
  }
  return 0;
};

export const isMoving = (state: TransitionState): boolean =>
  state.phase !== 'closed' && state.phase !== 'open';

export const isVisible = (state: TransitionState): boolean => state.phase !== 'closed';

const nextPhase = (
  phase: TransitionPhase,
  direction: TransitionDirection
): TransitionState => {
  if (phase === 'shrinking') {
    return { phase: 'turning', direction };
  }
  if (phase === 'turning') {
    return { phase: 'settling', direction };
  }
  return direction === 'opening' ? OPEN : CLOSED;
};

export const transitionReducer = (
  state: TransitionState,
  event: TransitionEvent
): TransitionState => {
  if (event.kind === 'abort') {
    return state.direction === 'opening' ? CLOSED : state.direction === 'closing' ? OPEN : state;
  }
  if (event.kind === 'open') {
    if (state.phase === 'open' || state.direction === 'opening') {
      return state;
    }
    return { phase: 'shrinking', direction: 'opening' };
  }
  if (event.kind === 'close') {
    if (state.phase === 'closed' || state.direction === 'closing') {
      return state;
    }
    return { phase: 'shrinking', direction: 'closing' };
  }
  if (event.phase !== state.phase || !isMoving(state)) {
    return state;
  }
  return nextPhase(state.phase, state.direction);
};

export const LAG_FRAME_MS = 40;
export const LAG_FRAME_COUNT = 3;

export const framesAreLagging = (durationsMs: readonly number[]): boolean =>
  durationsMs.length >= LAG_FRAME_COUNT &&
  durationsMs
    .slice(0, LAG_FRAME_COUNT)
    .every((duration) => duration > LAG_FRAME_MS);
