import { describe, expect, it } from 'vitest';
import { DASH, formatNumber, formatPercent, formatStepDate } from './format';

describe('formatStepDate', () => {
  it('keeps the calendar month of a UTC midnight date', () => {
    expect(formatStepDate('en', '2007-01-01')).toBe('January 2007');
    expect(formatStepDate('ru', '2007-01-01')).toBe('январь 2007 г.');
  });

  it('does not drift for dates across the year boundary', () => {
    expect(formatStepDate('en', '2025-01-01')).toBe('January 2025');
    expect(formatStepDate('en', '2024-12-01')).toBe('December 2024');
  });

  it('formats every month without shifting', () => {
    const months = Array.from({ length: 12 }, (_, index) =>
      formatStepDate('en', `2007-${String(index + 1).padStart(2, '0')}-01`)
    );
    expect(months).toEqual([
      'January 2007',
      'February 2007',
      'March 2007',
      'April 2007',
      'May 2007',
      'June 2007',
      'July 2007',
      'August 2007',
      'September 2007',
      'October 2007',
      'November 2007',
      'December 2007'
    ]);
  });

  it('returns a dash for an invalid date instead of throwing', () => {
    expect(formatStepDate('ru', '')).toBe(DASH);
    expect(formatStepDate('ru', 'not-a-date')).toBe(DASH);
    expect(formatStepDate('en', '2007-13-45')).toBe(DASH);
    expect(() => formatStepDate('en', '')).not.toThrow();
  });
});

describe('formatNumber', () => {
  it('renders a value rounding to zero without a minus sign', () => {
    expect(formatNumber('ru', -0.4, 0)).toBe('0');
    expect(formatNumber('en', -0.4, 0)).toBe('0');
    expect(formatNumber('ru', -0, 0)).toBe('0');
    expect(formatNumber('en', -0.04, 1)).toBe('0');
  });

  it('keeps genuine negative values negative', () => {
    expect(formatNumber('en', -0.5, 0)).toBe('-1');
    expect(formatNumber('en', -1.4, 0)).toBe('-1');
    expect(formatNumber('en', -0.05, 1)).toBe('-0.1');
    expect(formatNumber('en', -0.5, 1)).toBe('-0.5');
  });

  it('keeps positive values unchanged', () => {
    expect(formatNumber('en', 0.4, 0)).toBe('0');
    expect(formatNumber('en', 1.6, 0)).toBe('2');
  });
});

describe('formatPercent', () => {
  it('formats a share as a percentage', () => {
    expect(formatPercent('en', 0.5)).toBe('50%');
  });
});
