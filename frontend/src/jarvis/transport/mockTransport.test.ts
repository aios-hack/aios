import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { describe, expect, it } from 'vitest';
import { parseEventLine, type JarvisEvent } from './events';
import {
  FIXTURE_INDEX,
  createMockTransport,
  matchFixture,
  splitLines
} from './mockTransport';

const fixtureRoot = join(__dirname, '..', '..', '..', 'public', 'jarvis');

const readFixture = (file: string): string => {
  try {
    return readFileSync(join(fixtureRoot, 'fixtures', `${file}.jsonl`), 'utf-8');
  } catch {
    return readFileSync(join(fixtureRoot, 'fixtures-f', `${file}.jsonl`), 'utf-8');
  }
};

const fetchText = async (url: string): Promise<string> => {
  const match = /\/jarvis\/(fixtures|fixtures-f)\/([a-z0-9-]+)\.jsonl$/.exec(url);
  if (match === null) {
    throw new Error(`unexpected url ${url}`);
  }
  return readFixture(match[2]);
};

const collect = async (question: string): Promise<JarvisEvent[]> => {
  const transport = createMockTransport({ fetchText, delayMs: 0, wait: async () => undefined });
  const events: JarvisEvent[] = [];
  for await (const event of transport.ask(
    {
      sessionId: 's',
      question,
      lang: 'ru',
      context: {
        scenario: 'base',
        step: 96,
        date: '2015-01-01',
        selected_well: null,
        workspace: 'field',
        view: 'projection'
      }
    },
    new AbortController().signal
  )) {
    events.push(event);
  }
  return events;
};

describe('fixture routing', () => {
  it('routes each catalogued question to its own file', () => {
    expect(matchFixture('Почему закрыли скважину 51 в 2013?')).toBe('why-well-13');
    expect(matchFixture('Кто тянет ЧДД вниз?')).toBe('who-drags-npv');
    expect(matchFixture('Что случилось с фондом в 2015?')).toBe('field-in-2015');
    expect(matchFixture('Сравни base и whatif-injection-cut')).toBe('compare-scenarios');
    expect(matchFixture('Что такое ЧДД?')).toBe('what-is-npv');
    expect(matchFixture('Где посмотреть, кто с кем связан?')).toBe('where-is-connectivity');
  });

  it('falls back to the first fixture instead of throwing on a stranger question', () => {
    expect(FIXTURE_INDEX.map((entry) => entry.file)).toContain(matchFixture('лунная погода'));
  });
});

describe('every fixture line is a valid contract event', () => {
  for (const entry of FIXTURE_INDEX) {
    it(`${entry.file}: parses and follows the documented order`, () => {
      const lines = splitLines(readFixture(entry.file));
      const events = lines.map(parseEventLine);
      expect(events.every((event) => event !== null), entry.file).toBe(true);
      const types = events.map((event) => event?.type);
      expect(types[0]).toBe('scene');
      expect(types[types.length - 1]).toBe('done');
      expect(types.indexOf('caption')).toBeGreaterThan(types.lastIndexOf('card'));
      expect(types.indexOf('suggestions')).toBeGreaterThan(types.indexOf('caption'));
    });
  }
});

describe('mock transport replays a scene', () => {
  it('streams scene, cards, caption, suggestions and done in order', async () => {
    const events = await collect('Почему закрыли скважину 51 в 2013?');
    const types = events.map((event) => event.type);
    expect(types[0]).toBe('scene');
    expect(types).toContain('card');
    expect(types).toContain('caption');
    expect(types[types.length - 1]).toBe('done');
  });

  it('gives every card a provenance chip and never an empty payload', async () => {
    const events = await collect('Кто тянет ЧДД вниз?');
    const cards = events.filter((event) => event.type === 'card');
    expect(cards.length).toBeGreaterThan(0);
    for (const event of cards) {
      if (event.type !== 'card') {
        continue;
      }
      expect(event.card.provenance.length).toBeGreaterThan(0);
      expect(event.card.payload).not.toBeNull();
    }
  });

  it('reports an error event instead of throwing when no fixture is on disk', async () => {
    const transport = createMockTransport({
      fetchText: async () => {
        throw new Error('missing');
      },
      wait: async () => undefined
    });
    const events: JarvisEvent[] = [];
    for await (const event of transport.ask(
      {
        sessionId: 's',
        question: 'что угодно',
        lang: 'ru',
        context: {
          scenario: 'base',
          step: 0,
          date: '2007-01-01',
          selected_well: null,
          workspace: 'overview',
          view: 'fund'
        }
      },
      new AbortController().signal
    )) {
      events.push(event);
    }
    expect(events.length).toBe(1);
    expect(events[0].type).toBe('error');
    expect(events[0].type === 'error' && events[0].code).toBe('no-fixture');
  });

  it('stops streaming as soon as the caller aborts', async () => {
    const controller = new AbortController();
    const transport = createMockTransport({ fetchText, delayMs: 0, wait: async () => undefined });
    const events: JarvisEvent[] = [];
    for await (const event of transport.ask(
      {
        sessionId: 's',
        question: 'Что такое ЧДД?',
        lang: 'ru',
        context: {
          scenario: 'base',
          step: 224,
          date: '2025-09-01',
          selected_well: null,
          workspace: 'money',
          view: 'rank'
        }
      },
      controller.signal
    )) {
      events.push(event);
      controller.abort();
    }
    expect(events.length).toBe(1);
  });
});
