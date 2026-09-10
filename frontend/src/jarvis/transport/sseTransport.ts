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
  fetchImpl?: typeof fetch;
}

export const errorCodeOf = (status: number, body: string): string => {
  try {
    const parsed: unknown = JSON.parse(body);
    if (typeof parsed === 'object' && parsed !== null) {
      const code = (parsed as Record<string, unknown>).error;
      if (typeof code === 'string' && code.length > 0) {
        return code;
      }
    }
  } catch {
    return status === 503 ? 'no-api-key' : 'upstream';
  }
  return status === 503 ? 'no-api-key' : 'upstream';
};

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

export const createSseTransport = ({ fetchImpl }: SseOptions = {}): JarvisTransport => ({
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
      yield { type: 'error', code: 'upstream', message: 'jarvis service is unreachable' };
      return;
    }
    if (!response.ok || response.body === null) {
      let body = '';
      try {
        body = await response.text();
      } catch {
        body = '';
      }
      yield {
        type: 'error',
        code: errorCodeOf(response.status, body),
        message: `http ${response.status}`
      };
      return;
    }
    yield* readStream(response.body, signal);
  }
});

export interface JarvisCapabilities {
  ok: boolean;
  tts: boolean;
  stt: 'server' | 'browser' | 'none';
  docs: number;
  sessions: number;
}

export const OFFLINE: JarvisCapabilities = {
  ok: false,
  tts: false,
  stt: 'none',
  docs: 0,
  sessions: 0
};

export const readCapabilities = (ok: boolean, value: unknown): JarvisCapabilities => {
  if (typeof value !== 'object' || value === null) {
    return { ...OFFLINE, ok };
  }
  const record = value as Record<string, unknown>;
  const stt = record.stt;
  return {
    ok,
    tts: record.tts === true,
    stt: stt === 'server' || stt === 'browser' ? stt : 'none',
    docs: typeof record.docs === 'number' && Number.isFinite(record.docs) ? record.docs : 0,
    sessions:
      typeof record.sessions === 'number' && Number.isFinite(record.sessions)
        ? record.sessions
        : 0
  };
};

export const fetchCapabilities = async (
  fetchImpl?: typeof fetch
): Promise<JarvisCapabilities> => {
  const call = fetchImpl ?? fetch;
  try {
    const response = await call(HEALTH_URL, { method: 'GET' });
    if (response.status >= 500 && response.status !== 503) {
      return OFFLINE;
    }
    return readCapabilities(response.ok, await response.json());
  } catch {
    return OFFLINE;
  }
};

export const checkHealth = async (fetchImpl?: typeof fetch): Promise<boolean> =>
  (await fetchCapabilities(fetchImpl)).ok;
