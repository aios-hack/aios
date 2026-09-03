import { readdirSync, readFileSync } from 'node:fs';
import { join } from 'node:path';
import { describe, expect, it } from 'vitest';
import { parseEventLine } from '../transport/events';
import {
  readCompare,
  readError,
  readEventStrip,
  readFieldMap,
  readGlossary,
  readGuide,
  readMetric,
  readMetrics,
  readPattern,
  readRule,
  readRuleSummary,
  readSeries,
  readWell,
  readWellList
} from './cardPayloads';

const fixtureDir = join(__dirname, '..', '..', '..', 'public', 'jarvis', 'fixtures');

const readers: Record<string, (payload: unknown) => unknown> = {
  metric: (payload) => {
    const metrics = readMetrics(payload);
    return metrics.length === 0 ? null : metrics;
  },
  well: readWell,
  'well-list': readWellList,
  series: readSeries,
  rule: (payload: unknown) => readRule(payload) ?? readRuleSummary(payload),
  compare: readCompare,
  'event-strip': readEventStrip,
  'field-map': readFieldMap,
  pattern: readPattern,
  glossary: readGlossary,
  guide: readGuide
};

interface FixtureCard {
  type: string;
  payload: unknown;
}

const fixtureCards = (): { file: string; card: FixtureCard }[] => {
  const cards: { file: string; card: FixtureCard }[] = [];
  for (const file of readdirSync(fixtureDir)) {
    if (!file.endsWith('.jsonl')) {
      continue;
    }
    const text = readFileSync(join(fixtureDir, file), 'utf-8');
    for (const line of text.split('\n')) {
      if (line.trim().length === 0) {
        continue;
      }
      const event = parseEventLine(line);
      if (event !== null && event.type === 'card') {
        cards.push({ file, card: event.card as unknown as FixtureCard });
      }
    }
  }
  return cards;
};

describe('every fixture card passes its own validator', () => {
  const cards = fixtureCards();

  it('finds cards to check', () => {
    expect(cards.length).toBeGreaterThan(0);
  });

  for (const { file, card } of cards) {
    it(`${file}: ${card.type} payload is accepted`, () => {
      const reader = readers[card.type];
      expect(reader, `no validator for ${card.type}`).toBeTypeOf('function');
      expect(reader(card.payload), `${file} ${card.type}`).not.toBeNull();
    });
  }
});

describe('metric payloads arrive as a list, as the contract says', () => {
  it('reads the {metrics:[…]} shape the field_metrics tool returns', () => {
    const payload = {
      date: '2015-01-01',
      metrics: [
        { id: 'active_wells', label: 'фонд', value: 94, unit: '', delta: 0, spark: [] },
        { id: 'npv', label: 'ЧДД', value: 12, unit: 'руб.', delta: 3, spark: [] }
      ]
    };
    const metrics = readMetrics(payload);
    expect(metrics).toHaveLength(2);
    expect(metrics[0].id).toBe('active_wells');
    expect(metrics[1].value).toBe(12);
  });

  it('reads a bare array of metrics', () => {
    const metrics = readMetrics([
      { id: 'a', label: 'a', value: 1, unit: '', delta: null, spark: [] }
    ]);
    expect(metrics).toHaveLength(1);
  });

  it('still reads a single metric object', () => {
    const metrics = readMetrics({ id: 'a', label: 'a', value: 1 });
    expect(metrics).toHaveLength(1);
    expect(metrics[0].value).toBe(1);
  });

  it('drops entries that carry no number instead of inventing one', () => {
    const metrics = readMetrics({
      metrics: [
        { id: 'good', label: 'good', value: 5 },
        { id: 'bad', label: 'bad' },
        { id: 'worse', label: 'worse', value: 'много' }
      ]
    });
    expect(metrics.map((metric) => metric.id)).toEqual(['good']);
  });

  it('returns nothing for junk', () => {
    expect(readMetrics(null)).toEqual([]);
    expect(readMetrics('12')).toEqual([]);
    expect(readMetrics({ metrics: 'no' })).toEqual([]);
  });
});

describe('validators refuse malformed payloads instead of guessing', () => {
  it('rejects a metric with no label or value', () => {
    expect(readMetric({ label: 'ЧДД' })).toBeNull();
    expect(readMetric({ value: 12 })).toBeNull();
    expect(readMetric(null)).toBeNull();
  });

  it('rejects a well with no id or no rates', () => {
    expect(readWell({ liquid_rate: 1, injection_rate: 0 })).toBeNull();
    expect(readWell({ well: '45' })).toBeNull();
  });

  it('keeps a null watercut null rather than turning it into zero', () => {
    const well = readWell({
      well: '45',
      liquid_rate: 10,
      injection_rate: 0,
      watercut: null
    });
    expect(well?.watercut).toBeNull();
  });

  it('always yields an error payload, since that is the last resort card', () => {
    expect(readError(null).code).toBeTypeOf('string');
    expect(readError({ code: 'tool-failed' }).code).toBe('tool-failed');
  });
});
