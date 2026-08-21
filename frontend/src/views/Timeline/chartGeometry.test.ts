import { describe, expect, it } from 'vitest';
import { indexFromRatio, panelGeometry, yearTicks } from './chartGeometry';

const OPTIONS = { width: 100, top: 0, height: 20, total: 4 };

const pointCount = (segments: string[]): number =>
  segments.reduce((sum, segment) => sum + segment.trim().split(/\s+/).length, 0);

describe('panelGeometry', () => {
  it('plots one point per step of the horizon', () => {
    const geometry = panelGeometry([1, 2, 3, 4], OPTIONS);
    expect(pointCount(geometry.segments)).toBe(4);
    expect(geometry.min).toBe(1);
    expect(geometry.max).toBe(4);
  });

  it('breaks the line where a step carries no value', () => {
    const geometry = panelGeometry([1, 2, null, 4], OPTIONS);
    expect(geometry.segments).toHaveLength(2);
    expect(pointCount(geometry.segments)).toBe(3);
  });

  it('keeps the last step at the right edge when values are missing there', () => {
    const geometry = panelGeometry([1, 2, 3, null], OPTIONS);
    expect(geometry.segments).toHaveLength(1);
    const last = geometry.segments[0].split(/\s+/).pop() ?? '';
    expect(Number(last.split(',')[0])).toBeCloseTo((2 / 3) * 100, 1);
  });

  it('returns an empty plot when nothing is finite', () => {
    const geometry = panelGeometry([null, null], OPTIONS);
    expect(geometry.segments).toHaveLength(0);
  });

  it('spreads a constant series instead of dividing by zero', () => {
    const geometry = panelGeometry([5, 5, 5, 5], OPTIONS);
    expect(geometry.min).toBeLessThan(geometry.max);
    expect(pointCount(geometry.segments)).toBe(4);
  });
});

describe('yearTicks', () => {
  it('emits one tick per calendar year of the data', () => {
    const ticks = yearTicks(['2007-01-01', '2007-02-01', '2008-01-01', '2009-01-01'], {
      width: 100,
      total: 4
    });
    expect(ticks.map((tick) => tick.year)).toEqual(['2007', '2008', '2009']);
    expect(ticks[0].x).toBe(0);
  });

  it('thins the labels down to the requested maximum', () => {
    const dates = Array.from({ length: 12 }, (_, index) => `${2007 + index}-01-01`);
    const ticks = yearTicks(dates, { width: 100, total: dates.length, maxLabels: 4 });
    expect(ticks.length).toBeLessThanOrEqual(4);
    expect(ticks[0].year).toBe('2007');
  });
});

describe('indexFromRatio', () => {
  it('maps a click position to the nearest step', () => {
    expect(indexFromRatio(0, 5)).toBe(0);
    expect(indexFromRatio(0.5, 5)).toBe(2);
    expect(indexFromRatio(1, 5)).toBe(4);
  });

  it('clamps positions outside the plot', () => {
    expect(indexFromRatio(-0.4, 5)).toBe(0);
    expect(indexFromRatio(2.3, 5)).toBe(4);
  });
});
