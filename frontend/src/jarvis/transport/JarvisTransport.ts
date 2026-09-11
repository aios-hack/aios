import type { JarvisAskContext, JarvisEvent } from '@/jarvis/transport/events';

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
