import { describe, expect, it } from 'vitest';
import { compareWellIds } from './wellOrder';

const sorted = (ids: string[]): string[] => [...ids].sort(compareWellIds);

describe('compareWellIds', () => {
  it('orders bare numeric ids by value, not lexically', () => {
    expect(sorted(['10', '2', '9', '1'])).toEqual(['1', '2', '9', '10']);
  });

  it('orders prefixed ids by their numeric tail', () => {
    expect(sorted(['P10', 'P9', 'P2'])).toEqual(['P2', 'P9', 'P10']);
  });

  it('groups by prefix before comparing numbers', () => {
    expect(sorted(['P2', 'I10', 'I2', 'P1'])).toEqual(['I2', 'I10', 'P1', 'P2']);
  });

  it('pushes blank ids to the end instead of treating them as zero', () => {
    expect(sorted(['10', '', '2', '   '])).toEqual(['2', '10', '', '   ']);
  });

  it('separates ids that parse to the same number', () => {
    expect(compareWellIds('5', '5.0')).not.toBe(0);
    expect(compareWellIds('5', '5')).toBe(0);
  });

  it('falls back to text order when no digits are present', () => {
    expect(sorted(['abd', 'abc'])).toEqual(['abc', 'abd']);
  });

  it('is symmetric and transitive on a mixed fund', () => {
    const ids = ['P1', '10', '2', 'INJ-3', '', 'P10', 'P9'];
    const forward = sorted(ids);
    const backward = sorted([...ids].reverse());
    expect(forward).toEqual(backward);
    for (const a of ids) {
      for (const b of ids) {
        expect(Math.sign(compareWellIds(a, b)) + Math.sign(compareWellIds(b, a))).toBe(0);
      }
    }
  });
});
