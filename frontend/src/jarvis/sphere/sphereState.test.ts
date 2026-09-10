import { describe, expect, it } from 'vitest';
import {
  BREATH_PERIOD_HOVER_MS,
  BREATH_PERIOD_MS,
  ERROR_FLASH_MS,
  SMOOTH_TAU_MS,
  SPHERE_STATES,
  approach,
  breathAt,
  breathOfPhase,
  breathPeriodOf,
  dprCap,
  energyOf,
  errorAt,
  flowSpeedOf,
  haloScaleOf,
  readSpherePalette,
  spinSpeedOf
} from './sphereState';

describe('sphere energy by state', () => {
  it('rests at zero and peaks while thinking', () => {
    expect(energyOf('idle')).toBe(0);
    expect(energyOf('thinking')).toBe(1);
  });

  it('gives every named state a finite energy in 0..1', () => {
    for (const state of SPHERE_STATES) {
      const energy = energyOf(state);
      expect(energy, state).toBeGreaterThanOrEqual(0);
      expect(energy, state).toBeLessThanOrEqual(1);
    }
  });

  it('orders listening below speaking below thinking', () => {
    expect(energyOf('listening')).toBeLessThan(energyOf('speaking'));
    expect(energyOf('speaking')).toBeLessThan(energyOf('thinking'));
  });
});

describe('breathing', () => {
  it('breathes at 3.2 s in rest and speeds to 2 s on hover', () => {
    expect(breathPeriodOf('idle')).toBe(BREATH_PERIOD_MS);
    expect(breathPeriodOf('hover')).toBe(BREATH_PERIOD_HOVER_MS);
  });

  it('returns to the same phase after a full period', () => {
    expect(breathAt(0, BREATH_PERIOD_MS)).toBeCloseTo(
      breathAt(BREATH_PERIOD_MS, BREATH_PERIOD_MS),
      5
    );
  });

  it('stays inside 0..1 across the period', () => {
    for (let ms = 0; ms <= BREATH_PERIOD_MS; ms += 100) {
      const value = breathAt(ms, BREATH_PERIOD_MS);
      expect(value).toBeGreaterThanOrEqual(0);
      expect(value).toBeLessThanOrEqual(1);
    }
  });

  it('reads the same value from an accumulated phase as from elapsed time', () => {
    expect(breathOfPhase(0.25)).toBeCloseTo(breathAt(BREATH_PERIOD_MS / 4, BREATH_PERIOD_MS), 5);
  });

  it('grows the halo by a fifth on hover and leaves it alone otherwise', () => {
    expect(haloScaleOf('hover')).toBeCloseTo(1.2, 5);
    expect(haloScaleOf('idle')).toBe(1);
  });
});

describe('phase speeds change, phase itself never jumps', () => {
  it('turns and flows faster the more energy the sphere carries', () => {
    expect(spinSpeedOf(1)).toBeGreaterThan(spinSpeedOf(0));
    expect(flowSpeedOf(1)).toBeGreaterThan(flowSpeedOf(0));
  });

  it('eases a value towards its target instead of snapping to it', () => {
    const half = approach(0, 1, SMOOTH_TAU_MS, SMOOTH_TAU_MS);
    expect(half).toBeGreaterThan(0.5);
    expect(half).toBeLessThan(0.7);
    expect(approach(0, 1, SMOOTH_TAU_MS * 12, SMOOTH_TAU_MS)).toBeCloseTo(1, 4);
    expect(approach(0.3, 1, 0, SMOOTH_TAU_MS)).toBe(1);
  });
});

describe('error flash', () => {
  it('rises and falls inside 600 ms and is silent outside', () => {
    expect(errorAt(-1)).toBe(0);
    expect(errorAt(ERROR_FLASH_MS + 1)).toBe(0);
    expect(errorAt(ERROR_FLASH_MS / 2)).toBeCloseTo(1, 5);
  });
});

describe('device pixel ratio is capped at two', () => {
  it('never asks for more pixels than the spec allows', () => {
    expect(dprCap(3)).toBe(2);
    expect(dprCap(1.5)).toBe(1.5);
    expect(dprCap(0.5)).toBe(1);
  });
});

describe('palette reading falls back instead of throwing', () => {
  it('returns a colour for every token when there is no root to read', () => {
    const palette = readSpherePalette(null);
    expect(palette['--color-jarvis-body'].r).toBeGreaterThanOrEqual(0);
    expect(Object.keys(palette).length).toBe(7);
  });
});
