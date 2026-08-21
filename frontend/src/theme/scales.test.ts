import { describe, expect, it } from 'vitest';
import { areaRadius, ratioColor, watercutColor } from './scales';

describe('watercutColor', () => {
  it('walks from the oil end to the water end', () => {
    expect(watercutColor(0)).toContain('0.0%');
    expect(watercutColor(1)).toContain('100.0%');
    expect(watercutColor(0.5)).toContain('50.0%');
  });

  it('says unknown instead of pretending a value is zero', () => {
    expect(watercutColor(null)).toBe('var(--color-unknown)');
    expect(watercutColor(Number.NaN)).toBe('var(--color-unknown)');
  });

  it('clamps values that arrive outside the physical range', () => {
    expect(watercutColor(-0.4)).toBe(watercutColor(0));
    expect(watercutColor(1.7)).toBe(watercutColor(1));
  });
});

describe('ratioColor', () => {
  it('treats reaching the target as the healthy end', () => {
    expect(ratioColor(1)).toBe('var(--scale-ratio-high)');
    expect(ratioColor(1.4)).toBe('var(--scale-ratio-high)');
  });

  it('darkens towards danger as the well falls short', () => {
    expect(ratioColor(0)).toContain('0.0%');
    expect(ratioColor(0.5)).toContain('50.0%');
  });

  it('reports a missing measurement as unknown', () => {
    expect(ratioColor(null)).toBe('var(--color-unknown)');
  });
});

describe('areaRadius', () => {
  it('makes area proportional to the value, not the radius', () => {
    const min = 1;
    const max = 5;
    const quarter = areaRadius(25, 100, min, max);
    const full = areaRadius(100, 100, min, max);
    expect(full).toBeCloseTo(max, 6);
    expect(quarter - min).toBeCloseTo((full - min) / 2, 6);
  });

  it('falls back to the smallest marker for zero, negative and empty scales', () => {
    expect(areaRadius(0, 100, 1.2, 4.5)).toBe(1.2);
    expect(areaRadius(-8, 100, 1.2, 4.5)).toBe(1.2);
    expect(areaRadius(50, 0, 1.2, 4.5)).toBe(1.2);
  });

  it('never grows past the maximum radius on an outlier', () => {
    expect(areaRadius(500, 100, 1.2, 4.5)).toBe(4.5);
  });
});
