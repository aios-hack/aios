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
  '--color-jarvis-halo',
  '--color-jarvis-shadow'
] as const;

export type SphereToken = (typeof SPHERE_TOKENS)[number];
export type SpherePalette = Record<SphereToken, Rgb>;

const FALLBACK: Rgb = { r: 128, g: 176, b: 224, a: 1 };

export const readSpherePalette = (root: Element | null): SpherePalette =>
  readPalette(SPHERE_TOKENS, FALLBACK, root);

export const BREATH_PERIOD_MS = 3200;
export const BREATH_PERIOD_HOVER_MS = 2000;
export const ERROR_FLASH_MS = 600;
export const SMOOTH_TAU_MS = 350;

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

export const spinSpeedOf = (energy: number): number => 0.16 + 0.5 * energy;

export const flowSpeedOf = (energy: number): number => 0.35 + 0.6 * energy;

export const approach = (value: number, target: number, dtMs: number, tauMs: number): number => {
  if (tauMs <= 0 || dtMs <= 0) {
    return target;
  }
  return value + (target - value) * (1 - Math.exp(-dtMs / tauMs));
};

export const breathAt = (elapsedMs: number, periodMs: number): number =>
  0.5 + 0.5 * Math.sin((elapsedMs / periodMs) * Math.PI * 2);

export const breathOfPhase = (phase: number): number =>
  0.5 + 0.5 * Math.sin(phase * Math.PI * 2);

export const errorAt = (sinceStartMs: number): number => {
  if (sinceStartMs < 0 || sinceStartMs > ERROR_FLASH_MS) {
    return 0;
  }
  return Math.sin((sinceStartMs / ERROR_FLASH_MS) * Math.PI);
};

export const dprCap = (ratio: number): number => Math.min(Math.max(ratio, 1), 2);
