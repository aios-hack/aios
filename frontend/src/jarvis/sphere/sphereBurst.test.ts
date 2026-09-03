import { describe, expect, it } from 'vitest';
import { TRANSITION_PHASES } from '../transition';
import {
  COLLAPSE_MS,
  MATERIALIZE_MS,
  burstDurationOf,
  burstFrameAt,
  burstModeOf,
  burstStyle
} from './sphereBurst';

describe('burst mode follows the transition phase', () => {
  it('collapses while shrinking and materialises while settling', () => {
    expect(burstModeOf('shrinking')).toBe('collapse');
    expect(burstModeOf('settling')).toBe('materialize');
  });

  it('does nothing while the cube turns or rests closed', () => {
    expect(burstModeOf('turning')).toBe('none');
    expect(burstModeOf('closed')).toBe('none');
  });

  it('names a mode for every phase', () => {
    for (const phase of TRANSITION_PHASES) {
      expect(['none', 'collapse', 'materialize'], phase).toContain(burstModeOf(phase));
    }
  });
});

describe('the collapse shrinks to a point, then flashes out', () => {
  it('starts at full size and full opacity', () => {
    const frame = burstFrameAt('collapse', 0);
    expect(frame.scale).toBeCloseTo(1, 3);
    expect(frame.opacity).toBe(1);
    expect(frame.burst).toBe(0);
  });

  it('reaches its smallest point before the flash', () => {
    const held = burstFrameAt('collapse', COLLAPSE_MS * 0.6);
    const early = burstFrameAt('collapse', COLLAPSE_MS * 0.2);
    expect(held.scale).toBeLessThan(early.scale);
    expect(held.scale).toBeLessThan(0.3);
  });

  it('ends invisible, fully burst and larger than the shell', () => {
    const frame = burstFrameAt('collapse', COLLAPSE_MS);
    expect(frame.opacity).toBe(0);
    expect(frame.burst).toBe(1);
    expect(frame.scale).toBeGreaterThan(1);
  });

  it('never leaves the sphere visible after the flash', () => {
    expect(burstFrameAt('collapse', COLLAPSE_MS * 5).opacity).toBe(0);
  });
});

describe('the materialisation grows back out of the flash', () => {
  it('starts small, transparent and bursting', () => {
    const frame = burstFrameAt('materialize', 0);
    expect(frame.scale).toBeLessThan(0.4);
    expect(frame.opacity).toBe(0);
    expect(frame.burst).toBeGreaterThan(0.9);
  });

  it('settles at rest when the phase is over', () => {
    const frame = burstFrameAt('materialize', MATERIALIZE_MS);
    expect(frame.scale).toBe(1);
    expect(frame.opacity).toBe(1);
    expect(frame.burst).toBe(0);
  });

  it('grows monotonically in opacity', () => {
    const early = burstFrameAt('materialize', MATERIALIZE_MS * 0.15);
    const late = burstFrameAt('materialize', MATERIALIZE_MS * 0.6);
    expect(late.opacity).toBeGreaterThan(early.opacity);
    expect(late.scale).toBeGreaterThan(early.scale);
  });
});

describe('burst frames stay inside their contract', () => {
  it('keeps opacity and burst within zero and one for both modes', () => {
    for (const mode of ['collapse', 'materialize'] as const) {
      const duration = burstDurationOf(mode);
      for (let step = 0; step <= 20; step += 1) {
        const frame = burstFrameAt(mode, (duration * step) / 20);
        expect(frame.opacity, `${mode}@${step}`).toBeGreaterThanOrEqual(0);
        expect(frame.opacity, `${mode}@${step}`).toBeLessThanOrEqual(1);
        expect(frame.burst, `${mode}@${step}`).toBeGreaterThanOrEqual(0);
        expect(frame.burst, `${mode}@${step}`).toBeLessThanOrEqual(1);
        expect(frame.scale, `${mode}@${step}`).toBeGreaterThan(0);
      }
    }
  });

  it('holds the sphere still when there is nothing to play', () => {
    const frame = burstFrameAt('none', 999);
    expect(frame).toEqual({ scale: 1, opacity: 1, burst: 0 });
    expect(burstDurationOf('none')).toBe(0);
  });

  it('writes a transform and opacity a browser can apply', () => {
    const style = burstStyle(burstFrameAt('materialize', MATERIALIZE_MS * 0.5));
    expect(style.transform).toMatch(/^scale\(\d+\.\d+\)$/);
    expect(Number(style.opacity)).toBeGreaterThan(0);
  });
});
