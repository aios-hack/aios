import { describe, expect, it } from 'vitest';
import { bandGeometry, buildSparkline, collectPoints } from './series';

describe('collectPoints', () => {
  it('keeps the original index so gaps stay where they happened', () => {
    expect(collectPoints([1, null, 3])).toEqual([
      { index: 0, value: 1 },
      { index: 2, value: 3 }
    ]);
  });

  it('drops nulls and non-finite values instead of reading them as zero', () => {
    expect(collectPoints([null, undefined, Number.NaN, Number.POSITIVE_INFINITY])).toEqual([]);
  });
});

describe('buildSparkline', () => {
  const size = { width: 100, height: 20, current: 0 };

  it('spans the full width from the first step to the last', () => {
    const spark = buildSparkline([0, 5, 10], size);
    const points = spark.segments[0].split(' ');
    expect(points[0].split(',')[0]).toBe('0.00');
    expect(points[2].split(',')[0]).toBe('100.00');
  });

  it('breaks the line where data is missing instead of bridging the gap', () => {
    const spark = buildSparkline([1, null, 3], size);
    expect(spark.segments).toHaveLength(2);
  });

  it('places the marker on the current step and nowhere else', () => {
    const spark = buildSparkline([1, 2, 3], { ...size, current: 1 });
    expect(spark.marker?.x).toBeCloseTo(50, 6);
  });

  it('leaves the marker absent when the current step has no measurement', () => {
    const spark = buildSparkline([1, null, 3], { ...size, current: 1 });
    expect(spark.marker).toBeNull();
  });

  it('scales against the whole horizon, not only the measured part', () => {
    const partial = buildSparkline([1, 2], { ...size, total: 5 });
    const points = partial.segments[0].split(' ');
    expect(Number(points[1].split(',')[0])).toBeCloseTo(25, 6);
  });

  it('keeps a flat series visible instead of collapsing it onto one edge', () => {
    const flat = buildSparkline([4, 4, 4], size);
    expect(flat.min).toBeLessThan(flat.max);
    for (const point of flat.segments[0].split(' ')) {
      expect(Number(point.split(',')[1])).toBeCloseTo(10, 6);
    }
  });

  it('widens the extent so a requested baseline stays inside the frame', () => {
    const spark = buildSparkline([10, 12], { ...size, baseline: 0 });
    expect(spark.min).toBeLessThanOrEqual(0);
  });

  it('draws larger values higher up the box', () => {
    const spark = buildSparkline([0, 10], size);
    const [first, second] = spark.segments[0].split(' ');
    expect(Number(first.split(',')[1])).toBeGreaterThan(Number(second.split(',')[1]));
  });
});

describe('bandGeometry', () => {
  const geometry = buildSparkline([0, 10], { width: 100, height: 20, current: 0 });

  it('maps a corridor onto the same scale as the line', () => {
    const band = bandGeometry(geometry, 2.5, 7.5);
    expect(band?.y).toBeCloseTo(5, 6);
    expect(band?.height).toBeCloseTo(10, 6);
  });

  it('clips a corridor that runs past the drawn extent', () => {
    const band = bandGeometry(geometry, -100, 100);
    expect(band?.y).toBe(0);
    expect(band?.height).toBe(20);
  });

  it('reports no band when the corridor is empty or inverted', () => {
    expect(bandGeometry(geometry, 5, 5)).toBeNull();
    expect(bandGeometry(geometry, 8, 2)).toBeNull();
  });
});
