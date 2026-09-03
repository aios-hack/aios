import type { JarvisAskContext, JarvisEvent } from './events';

export interface JarvisAsk {
  sessionId: string;
  question: string;
  lang: string;
  context: JarvisAskContext;
}

export interface JarvisTransport {
  readonly mode: 'mock' | 'sse';
  ask(ask: JarvisAsk, signal: AbortSignal): AsyncIterable<JarvisEvent>;
}

export const QUESTION_LIMIT = 600;

export const sessionIdOf = (storage: Storage | null): string => {
  const key = 'aios-jarvis-session';
  const random = (): string =>
    typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function'
      ? crypto.randomUUID()
      : `s-${Math.random().toString(36).slice(2)}-${Date.now().toString(36)}`;
  if (storage === null) {
    return random();
  }
  try {
    const stored = storage.getItem(key);
    if (stored !== null && stored.length > 0) {
      return stored;
    }
    const next = random();
    storage.setItem(key, next);
    return next;
  } catch {
    return random();
  }
};
