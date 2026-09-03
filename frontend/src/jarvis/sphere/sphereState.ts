import { readPalette, type Rgb } from '../../views/shared/canvasColors';

export const SPHERE_STATES = [
  'idle',
  'hover',
  'listening',
  'thinking',
  'speaking',
  'error'
] as const;

export type SphereState = (typeof SPHERE_STATES)[number];

export const SPHERE_TOKENS = [
  '--color-jarvis-body',
  '--color-jarvis-pulse',
  '--color-jarvis-deep',
  '--color-jarvis-rim',
  '--color-jarvis-spark',
  '--color-jarvis-halo'
] as const;

export type SphereToken = (typeof SPHERE_TOKENS)[number];
export type SpherePalette = Record<SphereToken, Rgb>;

const FALLBACK: Rgb = { r: 128, g: 176, b: 224, a: 1 };

export const readSpherePalette = (root: Element | null): SpherePalette =>
  readPalette(SPHERE_TOKENS, FALLBACK, root);

export const BREATH_PERIOD_MS = 3200;
export const BREATH_PERIOD_HOVER_MS = 2000;
export const PULSE_DURATION_MS = 900;
export const PULSE_GAP_MIN_MS = 3000;
export const PULSE_GAP_MAX_MS = 6000;
export const ERROR_FLASH_MS = 600;

export const energyOf = (state: SphereState): number => {
  if (state === 'thinking') {
    return 1;
  }
  if (state === 'speaking') {
    return 0.55;
  }
  if (state === 'listening') {
    return 0.4;
  }
  if (state === 'hover') {
    return 0.2;
  }
  return 0;
};

export const breathPeriodOf = (state: SphereState): number =>
  state === 'hover' ? BREATH_PERIOD_HOVER_MS : BREATH_PERIOD_MS;

export const haloScaleOf = (state: SphereState): number => (state === 'hover' ? 1.2 : 1);

export const pulseGapOf = (state: SphereState, random: number): number => {
  const span = PULSE_GAP_MAX_MS - PULSE_GAP_MIN_MS;
  const base = PULSE_GAP_MIN_MS + span * Math.min(Math.max(random, 0), 1);
  if (state === 'thinking') {
    return base * 0.35;
  }
  if (state === 'listening' || state === 'speaking') {
    return base * 0.6;
  }
  return base;
};

export const breathAt = (elapsedMs: number, periodMs: number): number =>
  0.5 + 0.5 * Math.sin((elapsedMs / periodMs) * Math.PI * 2);

export const pulseAt = (sinceStartMs: number): number => {
  if (sinceStartMs < 0 || sinceStartMs > PULSE_DURATION_MS) {
    return 0;
  }
  const phase = sinceStartMs / PULSE_DURATION_MS;
  return Math.sin(phase * Math.PI) * (1 - phase * 0.35);
};

export const errorAt = (sinceStartMs: number): number => {
  if (sinceStartMs < 0 || sinceStartMs > ERROR_FLASH_MS) {
    return 0;
  }
  return Math.sin((sinceStartMs / ERROR_FLASH_MS) * Math.PI);
};

export const dprCap = (ratio: number): number => Math.min(Math.max(ratio, 1), 2);

export const speakingEnvelope = (elapsedMs: number, totalMs: number): number => {
  if (totalMs <= 0 || elapsedMs < 0 || elapsedMs > totalMs) {
    return 0;
  }
  const phase = elapsedMs / totalMs;
  const attack = Math.min(1, phase / 0.06);
  const release = Math.min(1, (1 - phase) / 0.12);
  const syllables = 0.55 + 0.45 * Math.abs(Math.sin(elapsedMs / 130));
  return Math.max(0, attack * release * syllables);
};
