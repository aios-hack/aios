import { describe, expect, it } from 'vitest';
import {
  CLOSED,
  OPEN,
  SETTLE_MS,
  SHRINK_MS,
  TOTAL_MS,
  TURN_MS,
  framesAreLagging,
  isMoving,
  isVisible,
  phaseDurationMs,
  transitionReducer,
  type TransitionState
} from './transition';

const step = (state: TransitionState): TransitionState =>
  transitionReducer(state, { kind: 'settled', phase: state.phase });

describe('opening walks the three takts and lands open', () => {
  it('goes closed → shrinking → turning → settling → open', () => {
    const shrinking = transitionReducer(CLOSED, { kind: 'open' });
    expect(shrinking).toEqual({ phase: 'shrinking', direction: 'opening' });
    const turning = step(shrinking);
    expect(turning).toEqual({ phase: 'turning', direction: 'opening' });
    const settling = step(turning);
    expect(settling).toEqual({ phase: 'settling', direction: 'opening' });
    expect(step(settling)).toEqual(OPEN);
  });

  it('runs the same choreography backwards on close', () => {
    let state = transitionReducer(OPEN, { kind: 'close' });
    expect(state).toEqual({ phase: 'shrinking', direction: 'closing' });
    state = step(state);
    expect(state.phase).toBe('turning');
    state = step(state);
    expect(state.phase).toBe('settling');
    expect(step(state)).toEqual(CLOSED);
  });
});

describe('the machine ignores what would derail it', () => {
  it('ignores a second open while already opening', () => {
    const shrinking = transitionReducer(CLOSED, { kind: 'open' });
    expect(transitionReducer(shrinking, { kind: 'open' })).toBe(shrinking);
  });

  it('ignores open when it is already open and close when already closed', () => {
    expect(transitionReducer(OPEN, { kind: 'open' })).toBe(OPEN);
    expect(transitionReducer(CLOSED, { kind: 'close' })).toBe(CLOSED);
  });

  it('ignores a settled event for a phase that is no longer current', () => {
    const turning: TransitionState = { phase: 'turning', direction: 'opening' };
    expect(transitionReducer(turning, { kind: 'settled', phase: 'shrinking' })).toBe(turning);
  });

  it('ignores a settled event while resting', () => {
    expect(transitionReducer(OPEN, { kind: 'settled', phase: 'open' })).toBe(OPEN);
    expect(transitionReducer(CLOSED, { kind: 'settled', phase: 'closed' })).toBe(CLOSED);
  });
});

describe('a reversal in the middle of a turn', () => {
  it('turns an opening run around into a closing run', () => {
    const turning = step(transitionReducer(CLOSED, { kind: 'open' }));
    const reversed = transitionReducer(turning, { kind: 'close' });
    expect(reversed).toEqual({ phase: 'shrinking', direction: 'closing' });
  });

  it('turns a closing run around into an opening run', () => {
    const turning = step(transitionReducer(OPEN, { kind: 'close' }));
    expect(transitionReducer(turning, { kind: 'open' })).toEqual({
      phase: 'shrinking',
      direction: 'opening'
    });
  });
});

describe('abort drops the console back where it started', () => {
  it('sends an aborted opening back to closed', () => {
    const turning = step(transitionReducer(CLOSED, { kind: 'open' }));
    expect(transitionReducer(turning, { kind: 'abort' })).toEqual(CLOSED);
  });

  it('sends an aborted closing back to open', () => {
    const turning = step(transitionReducer(OPEN, { kind: 'close' }));
    expect(transitionReducer(turning, { kind: 'abort' })).toEqual(OPEN);
  });

  it('leaves a resting machine alone', () => {
    expect(transitionReducer(OPEN, { kind: 'abort' })).toBe(OPEN);
  });
});

describe('phase predicates and timings match the specification', () => {
  it('keeps the console mounted from the first takt of opening', () => {
    expect(isVisible(CLOSED)).toBe(false);
    expect(isVisible({ phase: 'shrinking', direction: 'opening' })).toBe(true);
    expect(isVisible(OPEN)).toBe(true);
  });

  it('reports the three takts as moving and the rests as still', () => {
    expect(isMoving(CLOSED)).toBe(false);
    expect(isMoving(OPEN)).toBe(false);
    for (const phase of ['shrinking', 'turning', 'settling'] as const) {
      expect(isMoving({ phase, direction: 'opening' }), phase).toBe(true);
    }
  });

  it('spends 220 / 600 / 220 ms and totals 1040 ms', () => {
    expect(phaseDurationMs('shrinking')).toBe(SHRINK_MS);
    expect(phaseDurationMs('turning')).toBe(TURN_MS);
    expect(phaseDurationMs('settling')).toBe(SETTLE_MS);
    expect(phaseDurationMs('open')).toBe(0);
    expect(TOTAL_MS).toBe(1040);
  });
});

describe('lag insurance switches to a crossfade', () => {
  it('calls three slow frames in a row lagging', () => {
    expect(framesAreLagging([48, 52, 60])).toBe(true);
  });

  it('does not call a single hiccup lagging', () => {
    expect(framesAreLagging([60, 16, 16])).toBe(false);
    expect(framesAreLagging([16, 16, 16])).toBe(false);
  });

  it('needs three measured frames before it decides anything', () => {
    expect(framesAreLagging([90, 90])).toBe(false);
    expect(framesAreLagging([])).toBe(false);
  });
});
