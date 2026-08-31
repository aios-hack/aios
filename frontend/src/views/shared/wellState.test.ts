import { describe, expect, it } from 'vitest';
import { npvFill } from './wellState';
import { npvCeilingOf } from './wellFacts';

describe('npvFill', () => {
  it('marks a well with no npv entry as unknown rather than colouring it', () => {
    expect(npvFill(undefined, 100)).toBe('var(--color-unknown)');
  });

  it('marks every well unknown when the ceiling is degenerate', () => {
    expect(npvFill(0, 0)).toBe('var(--color-unknown)');
    expect(npvFill(5, 0)).toBe('var(--color-unknown)');
    expect(npvFill(-5, 0)).toBe('var(--color-unknown)');
    expect(npvFill(5, -1)).toBe('var(--color-unknown)');
  });

  it('never reports a degenerate ceiling as a mid-scale reading', () => {
    expect(npvFill(0, 0)).not.toBe('var(--scale-ratio-mid)');
    expect(npvFill(1, 0)).not.toBe('var(--scale-ratio-mid)');
  });

  it('still colours a real ratio once the ceiling is measurable', () => {
    expect(npvFill(-5, 100)).toBe('var(--scale-ratio-low)');
    expect(npvFill(100, 100)).not.toBe('var(--color-unknown)');
    expect(npvFill(50, 100)).not.toBe('var(--color-unknown)');
  });

  it('treats an empty npv file as unmeasured across the field', () => {
    const ceiling = npvCeilingOf(new Map());
    expect(ceiling).toBe(0);
    expect(npvFill(0, ceiling)).toBe('var(--color-unknown)');
  });

  it('treats an all-zero npv file as unmeasured rather than mid-scale', () => {
    const ceiling = npvCeilingOf(new Map([['W1', 0], ['W2', 0]]));
    expect(ceiling).toBe(0);
    expect(npvFill(0, ceiling)).toBe('var(--color-unknown)');
  });
});
