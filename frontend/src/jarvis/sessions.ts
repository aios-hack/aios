import { parseEvent, parseEventLine, type JarvisEvent } from './transport/events';
import { parseSseChunk } from './transport/sseTransport';
import { emptyScenes, scenesReducer, selectSceneAt, type ScenesState } from './scenes';

export const SESSION_KEY = 'aios-jarvis-session-id';
export const SESSIONS_URL = '/api/jarvis/sessions';
export const BRIEFING_URL = '/api/jarvis/briefing';
const BLANK = '\n\n';

export interface SessionRow {
  id: string;
  started: string;
  last: string;
  scenes: number;
  first_question: string;
}

const isRecord = (value: unknown): value is Record<string, unknown> =>
  typeof value === 'object' && value !== null && !Array.isArray(value);

const str = (value: unknown, fallback = ''): string =>
  typeof value === 'string' ? value : fallback;

export const newSessionId = (): string =>
  typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function'
    ? crypto.randomUUID()
    : `s-${Math.random().toString(36).slice(2)}-${Date.now().toString(36)}`;

export const storedSessionId = (storage: Storage | null): string => {
  if (storage === null) {
    return newSessionId();
  }
  try {
    const found = storage.getItem(SESSION_KEY);
    if (found !== null && found.length > 0) {
      return found;
    }
    const next = newSessionId();
    storage.setItem(SESSION_KEY, next);
    return next;
  } catch {
    return newSessionId();
  }
};

export const rememberSessionId = (storage: Storage | null, id: string): void => {
  if (storage === null) {
    return;
  }
  try {
    storage.setItem(SESSION_KEY, id);
  } catch {
    return;
  }
};

export const readSessionRows = (value: unknown): SessionRow[] => {
  const holder = isRecord(value) ? value.sessions : value;
  if (!Array.isArray(holder)) {
    return [];
  }
  return holder.filter(isRecord).flatMap((row) => {
    const id = str(row.id);
    if (id.length === 0) {
      return [];
    }
    return [
      {
        id,
        started: str(row.started),
        last: str(row.last),
        scenes: typeof row.scenes === 'number' && Number.isFinite(row.scenes) ? row.scenes : 0,
        first_question: str(row.first_question)
      }
    ];
  });
};

export const readStoredEvents = (value: unknown): JarvisEvent[] => {
  const holder = isRecord(value) ? value.events : value;
  if (!Array.isArray(holder)) {
    return [];
  }
  const collected: JarvisEvent[] = [];
  for (const raw of holder) {
    const event = parseEvent(raw);
    if (event !== null) {
      collected.push(event);
    }
  }
  return collected;
};

export const replayEvents = (
  events: readonly JarvisEvent[],
  from: ScenesState = emptyScenes
): ScenesState => {
  const replayed = events.reduce(
    (state, event) => scenesReducer(state, event),
    from
  );
  return selectSceneAt(replayed, replayed.scenes.length - 1);
};

export const fetchSessionRows = async (fetchImpl?: typeof fetch): Promise<SessionRow[]> => {
  const call = fetchImpl ?? fetch;
  try {
    const response = await call(SESSIONS_URL, { method: 'GET' });
    if (!response.ok) {
      return [];
    }
    return readSessionRows(await response.json());
  } catch {
    return [];
  }
};

export const fetchSessionEvents = async (
  id: string,
  fetchImpl?: typeof fetch
): Promise<JarvisEvent[]> => {
  const call = fetchImpl ?? fetch;
  try {
    const response = await call(`${SESSIONS_URL}/${encodeURIComponent(id)}`, {
      method: 'GET'
    });
    if (!response.ok) {
      return [];
    }
    return readStoredEvents(await response.json());
  } catch {
    return [];
  }
};

export const briefingUrl = (
  sessionId: string,
  lang: string,
  scenario: string,
  step: number
): string => {
  const params = new URLSearchParams({
    session_id: sessionId,
    lang,
    scenario,
    step: String(step)
  });
  return `${BRIEFING_URL}?${params.toString()}`;
};

export const fetchBriefing = async (
  sessionId: string,
  lang: string,
  scenario: string,
  step: number,
  fetchImpl?: typeof fetch
): Promise<JarvisEvent[]> => {
  const call = fetchImpl ?? fetch;
  try {
    const response = await call(briefingUrl(sessionId, lang, scenario, step), {
      method: 'GET'
    });
    if (!response.ok) {
      return [];
    }
    const body = await response.text();
    const { frames } = parseSseChunk(body.endsWith(BLANK) ? body : body + BLANK);
    const collected: JarvisEvent[] = [];
    for (const frame of frames) {
      const event = parseEventLine(frame.data);
      if (event !== null) {
        collected.push(event);
      }
    }
    return collected;
  } catch {
    return [];
  }
};
