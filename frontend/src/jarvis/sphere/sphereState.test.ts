import { describe, expect, it } from 'vitest';
import {
  BREATH_PERIOD_HOVER_MS,
  BREATH_PERIOD_MS,
  ERROR_FLASH_MS,
  PULSE_DURATION_MS,
  PULSE_GAP_MAX_MS,
  PULSE_GAP_MIN_MS,
  SPHERE_STATES,
  breathAt,
  breathPeriodOf,
  dprCap,
  energyOf,
  errorAt,
  haloScaleOf,
  pulseAt,
  pulseGapOf,
  readSpherePalette,
  speakingEnvelope
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

  it('grows the halo by a fifth on hover and leaves it alone otherwise', () => {
    expect(haloScaleOf('hover')).toBeCloseTo(1.2, 5);
    expect(haloScaleOf('idle')).toBe(1);
  });
});

describe('pulse waves are rare events, not a strobe', () => {
  it('keeps the resting gap inside the 3..6 s window from the moodboard', () => {
    expect(pulseGapOf('idle', 0)).toBe(PULSE_GAP_MIN_MS);
    expect(pulseGapOf('idle', 1)).toBe(PULSE_GAP_MAX_MS);
    expect(pulseGapOf('idle', 0.5)).toBe((PULSE_GAP_MIN_MS + PULSE_GAP_MAX_MS) / 2);
  });

  it('shortens the gap while thinking', () => {
    expect(pulseGapOf('thinking', 0.5)).toBeLessThan(pulseGapOf('idle', 0.5));
  });

  it('is silent outside the wave and peaks inside it', () => {
    expect(pulseAt(-1)).toBe(0);
    expect(pulseAt(PULSE_DURATION_MS + 1)).toBe(0);
    expect(pulseAt(PULSE_DURATION_MS / 2)).toBeGreaterThan(0.5);
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

describe('speaking envelope is synthetic, not measured', () => {
  it('is silent before the phrase starts and after it ends', () => {
    expect(speakingEnvelope(-1, 1000)).toBe(0);
    expect(speakingEnvelope(1001, 1000)).toBe(0);
    expect(speakingEnvelope(10, 0)).toBe(0);
  });

  it('opens and closes the phrase quieter than the middle', () => {
    const middle = speakingEnvelope(500, 1000);
    expect(speakingEnvelope(1, 1000)).toBeLessThan(middle);
    expect(speakingEnvelope(999, 1000)).toBeLessThan(middle);
  });
});

describe('palette reading falls back instead of throwing', () => {
  it('returns a colour for every token when there is no root to read', () => {
    const palette = readSpherePalette(null);
    expect(palette['--color-jarvis-body'].r).toBeGreaterThanOrEqual(0);
    expect(Object.keys(palette).length).toBe(6);
  });
});
