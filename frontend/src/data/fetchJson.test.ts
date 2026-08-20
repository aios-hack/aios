import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { DEFAULT_SCENARIO_ID, isSafeScenarioId, scenarioDataUrl } from '../state/ScenarioContext';
import { fetchJson, InvalidPayloadError } from './fetchJson';
import { loadJson, readCachedJson } from './jsonCache';

interface Payload {
  ok: true;
}

const isPayload = (data: unknown): data is Payload =>
  typeof data === 'object' && data !== null && (data as Payload).ok === true;

const respond = (body: unknown) =>
  Promise.resolve({ ok: true, json: () => Promise.resolve(body) });

afterEach(() => {
  vi.unstubAllGlobals();
});

describe('fetchJson', () => {
  it('rejects a body that does not match the validator', async () => {
    vi.stubGlobal('fetch', vi.fn(() => respond({ ok: false })));
    await expect(fetchJson('/data/x.json', isPayload)).rejects.toBeInstanceOf(
      InvalidPayloadError
    );
  });

  it('rejects a body that is not valid json at all', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(() =>
        Promise.resolve({ ok: true, json: () => Promise.reject(new SyntaxError('bad')) })
      )
    );
    await expect(fetchJson('/data/x.json', isPayload)).rejects.toBeInstanceOf(
      InvalidPayloadError
    );
  });

  it('reports the failing url so a broken artifact is identifiable', async () => {
    vi.stubGlobal('fetch', vi.fn(() => respond({ ok: false })));
    await expect(fetchJson('/data/npv.json', isPayload)).rejects.toThrow('/data/npv.json');
  });

  it('surfaces the status code for a non-ok response', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(() => Promise.resolve({ ok: false, status: 404, json: () => Promise.resolve({}) }))
    );
    await expect(fetchJson('/data/x.json', isPayload)).rejects.toThrow('404');
  });

  it('aborts the request when the caller signal aborts', async () => {
    const controller = new AbortController();
    vi.stubGlobal(
      'fetch',
      vi.fn(
        (_url: string, init: RequestInit) =>
          new Promise((_resolve, reject) => {
            init.signal?.addEventListener('abort', () => reject(new Error('aborted')));
          })
      )
    );
    const promise = fetchJson('/data/x.json', isPayload, controller.signal);
    controller.abort();
    await expect(promise).rejects.toThrow('aborted');
  });

  it('never sends credentials with an artifact request', async () => {
    const spy = vi.fn((_url: string, init: RequestInit) => {
      void init;
      return respond({ ok: true });
    });
    vi.stubGlobal('fetch', spy);
    await fetchJson('/data/x.json', isPayload);
    expect(spy.mock.calls[0][1]).toMatchObject({ credentials: 'omit' });
  });
});

describe('jsonCache', () => {
  beforeEach(() => {
    vi.stubGlobal('fetch', vi.fn(() => respond({ ok: true })));
  });

  it('issues a single request when the same url is asked for concurrently', async () => {
    const [a, b] = await Promise.all([
      loadJson('/data/same.json', isPayload),
      loadJson('/data/same.json', isPayload)
    ]);
    expect(a).toEqual(b);
    expect((globalThis.fetch as ReturnType<typeof vi.fn>).mock.calls).toHaveLength(1);
  });

  it('serves a settled url from cache without refetching', async () => {
    await loadJson('/data/settled.json', isPayload);
    expect(readCachedJson('/data/settled.json', isPayload)).toEqual({ ok: true });
    expect((globalThis.fetch as ReturnType<typeof vi.fn>).mock.calls).toHaveLength(1);
  });

  it('returns null from the cache for a url never loaded', () => {
    expect(readCachedJson('/data/missing.json', isPayload)).toBeNull();
  });

  it('lets a failed url be retried instead of caching the failure', async () => {
    vi.stubGlobal(
      'fetch',
      vi
        .fn()
        .mockImplementationOnce(() => Promise.reject(new Error('offline')))
        .mockImplementationOnce(() => respond({ ok: true }))
    );
    await expect(loadJson('/data/retry.json', isPayload)).rejects.toThrow('offline');
    await expect(loadJson('/data/retry.json', isPayload)).resolves.toEqual({ ok: true });
  });
});

describe('scenario url safety', () => {
  it('accepts plain scenario ids', () => {
    expect(isSafeScenarioId('what_if')).toBe(true);
    expect(scenarioDataUrl('what_if', 'npv.json')).toBe('/data/what_if/npv.json');
  });

  it('refuses a traversal id and falls back to the default path', () => {
    expect(isSafeScenarioId('../../etc')).toBe(false);
    expect(scenarioDataUrl('../../etc', 'npv.json')).toBe('/data/npv.json');
  });

  it('refuses a slashed or empty id', () => {
    expect(isSafeScenarioId('a/b')).toBe(false);
    expect(isSafeScenarioId('')).toBe(false);
    expect(scenarioDataUrl(DEFAULT_SCENARIO_ID, 'npv.json')).toBe('/data/npv.json');
  });

  it('refuses an id longer than the allowed length', () => {
    expect(isSafeScenarioId('a'.repeat(65))).toBe(false);
    expect(scenarioDataUrl('a'.repeat(65), 'npv.json')).toBe('/data/npv.json');
  });
});
