import { describe, expect, it } from 'vitest';
import type { TimelineWellRow } from '../../api/types';
import { readingText } from './readings';

const t = (key: string): string => key;

const row = (overrides: Partial<TimelineWellRow> = {}): TimelineWellRow => ({
  well: '1',
  availability: 'AVAILABLE',
  role: 'PROD',
  operating_status: 'OPEN',
  setpoint: 10,
  liquid_rate: 10,
  injection_rate: 0,
  bhp: 100,
  watercut: 0.7376,
  fact_to_target: 0.95,
  cumulative_liquid: 0,
  ...overrides
});

describe('readingText', () => {
  it('speaks a share as a percentage, not as a raw float', () => {
    const text = readingText({ lang: 'ru', t, metric: 'watercut', row: row() });
    expect(text).not.toContain('0.7376');
    expect(text).toContain('%');
  });

  it('says a value is unmeasured rather than reading out null', () => {
    expect(readingText({ lang: 'ru', t, metric: 'watercut', row: row({ watercut: null }) })).toBe(
      'chrono.value.unknown'
    );
    expect(
      readingText({ lang: 'ru', t, metric: 'ratio', row: row({ fact_to_target: null }) })
    ).toBe('chrono.value.unknown');
  });

  it('reports a missing row instead of inventing a reading', () => {
    expect(readingText({ lang: 'ru', t, metric: 'watercut', row: undefined })).toBe(
      'chrono.value.unknown'
    );
    expect(readingText({ lang: 'ru', t, metric: 'npv', row: undefined })).toBe(
      'chrono.value.unknown'
    );
  });

  it('names the operating mode through the dictionary, not by its raw code', () => {
    expect(readingText({ lang: 'ru', t, metric: 'mode', row: row() })).toMatch(/^chrono\.mode\./);
  });

  it('formats a money figure with the shared number formatter', () => {
    const text = readingText({ lang: 'ru', t, metric: 'npv', row: undefined, npv: 1234.5 });
    expect(text).not.toBe('1234.5');
    expect(text).toMatch(/\d/);
  });
});
