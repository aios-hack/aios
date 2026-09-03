import { SETTLE_MS, SHRINK_MS, type TransitionPhase } from '../transition';

export type BurstMode = 'none' | 'collapse' | 'materialize';

export interface BurstFrame {
  scale: number;
  opacity: number;
  burst: number;
}

export const COLLAPSE_MS = SHRINK_MS + 200;
export const MATERIALIZE_MS = SETTLE_MS + 180;
export const COLLAPSE_HOLD = 0.62;

const clamp01 = (value: number): number => Math.min(Math.max(value, 0), 1);

export const burstModeOf = (phase: TransitionPhase): BurstMode => {
  if (phase === 'shrinking') {
    return 'collapse';
  }
  if (phase === 'settling' || phase === 'open') {
    return 'materialize';
  }
  return 'none';
};

export const burstDurationOf = (mode: BurstMode): number =>
  mode === 'collapse' ? COLLAPSE_MS : mode === 'materialize' ? MATERIALIZE_MS : 0;

const collapseFrame = (t: number): BurstFrame => {
  if (t < COLLAPSE_HOLD) {
    const inner = t / COLLAPSE_HOLD;
    return {
      scale: 1 - 0.82 * inner * inner,
      opacity: 1,
      burst: 0.18 * inner
    };
  }
  const flash = (t - COLLAPSE_HOLD) / (1 - COLLAPSE_HOLD);
  return {
    scale: 0.18 + 2.1 * flash,
    opacity: 1 - flash * flash,
    burst: 0.35 + 0.65 * flash
  };
};

const materializeFrame = (t: number): BurstFrame => {
  const eased = 1 - Math.pow(1 - t, 3);
  const spark = Math.exp(-Math.pow(t * 4.5, 2.0));
  return {
    scale: 0.24 + 0.76 * eased + Math.sin(eased * Math.PI) * 0.12,
    opacity: clamp01(t * 3.2),
    burst: clamp01(spark + (1 - eased) * 0.5)
  };
};

export const burstFrameAt = (mode: BurstMode, elapsedMs: number): BurstFrame => {
  if (mode === 'none') {
    return { scale: 1, opacity: 1, burst: 0 };
  }
  const duration = burstDurationOf(mode);
  const t = clamp01(elapsedMs / duration);
  if (mode === 'collapse') {
    return t >= 1 ? { scale: 2.28, opacity: 0, burst: 1 } : collapseFrame(t);
  }
  return t >= 1 ? { scale: 1, opacity: 1, burst: 0 } : materializeFrame(t);
};

export const burstStyle = (frame: BurstFrame): Record<string, string> => ({
  transform: `scale(${frame.scale.toFixed(4)})`,
  opacity: frame.opacity.toFixed(4)
});
