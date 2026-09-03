import { parseEventLine, type JarvisEvent } from './events';
import type { JarvisAsk, JarvisTransport } from './JarvisTransport';

export const ASK_URL = '/api/jarvis/ask';
export const HEALTH_URL = '/api/jarvis/health';
export const CANCEL_URL = '/api/jarvis/cancel';

export interface SseFrame {
  data: string;
}

export const parseSseChunk = (
  buffer: string
): { frames: SseFrame[]; rest: string } => {
  const frames: SseFrame[] = [];
  const normalised = buffer.replace(/\r\n/g, '\n');
  const parts = normalised.split('\n\n');
  const rest = parts.pop() ?? '';
  for (const block of parts) {
    const data = block
      .split('\n')
      .filter((line) => line.startsWith('data:'))
      .map((line) => line.slice(5).replace(/^ /, ''))
      .join('\n');
    if (data.length > 0) {
      frames.push({ data });
    }
  }
  return { frames, rest };
};

export const askBody = (ask: JarvisAsk): string =>
  JSON.stringify({
    session_id: ask.sessionId,
    question: ask.question,
    lang: ask.lang,
    context: ask.context
  });

interface SseOptions {
  fallback?: JarvisTransport;
  onDegrade?: () => void;
  fetchImpl?: typeof fetch;
}

const readStream = async function* (
  body: ReadableStream<Uint8Array>,
  signal: AbortSignal
): AsyncIterable<JarvisEvent> {
  const reader = body.getReader();
  const decoder = new TextDecoder();
  let buffer = '';
  try {
    while (!signal.aborted) {
      const { done, value } = await reader.read();
      if (done) {
        break;
      }
      buffer += decoder.decode(value, { stream: true });
      const { frames, rest } = parseSseChunk(buffer);
      buffer = rest;
      for (const frame of frames) {
        const event = parseEventLine(frame.data);
        if (event !== null) {
          yield event;
        }
      }
    }
  } finally {
    reader.releaseLock();
  }
};

export const createSseTransport = ({
  fallback,
  onDegrade,
  fetchImpl
}: SseOptions = {}): JarvisTransport => ({
  mode: 'sse',
  async *ask(ask: JarvisAsk, signal: AbortSignal): AsyncIterable<JarvisEvent> {
    const call = fetchImpl ?? fetch;
    let response: Response;
    try {
      response = await call(ASK_URL, {
        method: 'POST',
        headers: { 'content-type': 'application/json' },
        body: askBody(ask),
        signal
      });
    } catch {
      if (fallback === undefined) {
        yield { type: 'error', code: 'upstream', message: 'fetch failed' };
        return;
      }
      onDegrade?.();
      yield* fallback.ask(ask, signal);
      return;
    }
    if (!response.ok || response.body === null) {
      if (response.status === 503 || fallback === undefined) {
        yield {
          type: 'error',
          code: response.status === 503 ? 'no-api-key' : 'upstream',
          message: `http ${response.status}`
        };
        if (fallback !== undefined) {
          onDegrade?.();
          yield* fallback.ask(ask, signal);
        }
        return;
      }
      onDegrade?.();
      yield* fallback.ask(ask, signal);
      return;
    }
    yield* readStream(response.body, signal);
  }
});

export const checkHealth = async (fetchImpl?: typeof fetch): Promise<boolean> => {
  const call = fetchImpl ?? fetch;
  try {
    const response = await call(HEALTH_URL, { method: 'GET' });
    return response.ok;
  } catch {
    return false;
  }
};
