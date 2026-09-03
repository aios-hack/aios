import { parseEventLine, type JarvisEvent } from './events';
import type { JarvisAsk, JarvisTransport } from './JarvisTransport';

export const FIXTURE_DIR = '/jarvis/fixtures';

export interface FixtureEntry {
  file: string;
  keywords: string[];
}

export const FIXTURE_INDEX: readonly FixtureEntry[] = [
  {
    file: 'why-well-13',
    keywords: ['почему', 'закрыл', 'останов', 'работает', 'why', 'shut', 'closed']
  },
  { file: 'who-drags-npv', keywords: ['тянет', 'худш', 'вниз', 'worst', 'drag', 'down'] },
  { file: 'field-in-2015', keywords: ['фонд', '2015', 'случилось', 'fund', 'happened'] },
  {
    file: 'compare-scenarios',
    keywords: ['сравни', 'whatif', 'compare', 'scenario', 'сценар']
  },
  { file: 'what-is-npv', keywords: ['что такое', 'чдд', 'npv', 'what is', 'термин'] },
  {
    file: 'where-is-connectivity',
    keywords: ['где', 'связ', 'кто с кем', 'where', 'connect', 'граф']
  }
];

export const matchFixture = (question: string): string => {
  const text = question.toLowerCase();
  let best = FIXTURE_INDEX[0];
  let bestScore = 0;
  for (const entry of FIXTURE_INDEX) {
    const score = entry.keywords.reduce(
      (total, keyword) => total + (text.includes(keyword) ? keyword.length : 0),
      0
    );
    if (score > bestScore) {
      best = entry;
      bestScore = score;
    }
  }
  return best.file;
};

export const splitLines = (text: string): string[] =>
  text.split('\n').filter((line) => line.trim().length > 0);

export interface MockOptions {
  fetchText?: (url: string) => Promise<string>;
  delayMs?: number;
  wait?: (ms: number, signal: AbortSignal) => Promise<void>;
}

const defaultFetchText = async (url: string): Promise<string> => {
  const response = await fetch(url);
  if (!response.ok) {
    throw new Error(`fixture ${url} is missing`);
  }
  return response.text();
};

const defaultWait = (ms: number, signal: AbortSignal): Promise<void> =>
  new Promise((resolve, reject) => {
    if (signal.aborted) {
      reject(signal.reason instanceof Error ? signal.reason : new Error('aborted'));
      return;
    }
    const id = setTimeout(() => {
      signal.removeEventListener('abort', onAbort);
      resolve();
    }, ms);
    const onAbort = () => {
      clearTimeout(id);
      reject(signal.reason instanceof Error ? signal.reason : new Error('aborted'));
    };
    signal.addEventListener('abort', onAbort, { once: true });
  });

export const loadFixture = (
  file: string,
  fetchText: (url: string) => Promise<string>
): Promise<string> => fetchText(`${FIXTURE_DIR}/${file}.jsonl`);

export const createMockTransport = ({
  fetchText = defaultFetchText,
  delayMs = 320,
  wait = defaultWait
}: MockOptions = {}): JarvisTransport => ({
  mode: 'mock',
  async *ask(ask: JarvisAsk, signal: AbortSignal): AsyncIterable<JarvisEvent> {
    let text: string;
    try {
      text = await loadFixture(matchFixture(ask.question), fetchText);
    } catch {
      yield { type: 'error', code: 'no-fixture', message: 'fixture missing' };
      return;
    }
    for (const line of splitLines(text)) {
      if (signal.aborted) {
        return;
      }
      const event = parseEventLine(line);
      if (event === null) {
        continue;
      }
      if (event.type === 'card' || event.type === 'caption') {
        try {
          await wait(delayMs, signal);
        } catch {
          return;
        }
      }
      yield event;
    }
  }
});
