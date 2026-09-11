export class InvalidPayloadError extends Error {
  constructor(url: string) {
    super(`invalid payload: ${url}`);
    this.name = 'InvalidPayloadError';
  }
}

const TIMEOUT_MS = 15000;

export const fetchJson = async <T,>(
  url: string,
  validate: (data: unknown) => data is T,
  signal?: AbortSignal
): Promise<T> => {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), TIMEOUT_MS);
  const onAbort = () => controller.abort();
  signal?.addEventListener('abort', onAbort, { once: true });
  try {
    const response = await fetch(url, {
      signal: controller.signal,
      credentials: 'omit'
    });
    if (!response.ok) {
      throw new Error(String(response.status));
    }
    let data: unknown;
    try {
      data = await response.json();
    } catch {
      throw new InvalidPayloadError(url);
    }
    if (!validate(data)) {
      throw new InvalidPayloadError(url);
    }
    return data;
  } finally {
    clearTimeout(timer);
    signal?.removeEventListener('abort', onAbort);
  }
};
