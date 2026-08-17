export class InvalidPayloadError extends Error {
  constructor(url: string) {
    super(`invalid payload: ${url}`);
    this.name = 'InvalidPayloadError';
  }
}

export const fetchJson = async <T,>(
  url: string,
  validate: (data: unknown) => data is T,
  signal?: AbortSignal
): Promise<T> => {
  const response = await fetch(url, signal ? { signal } : undefined);
  if (!response.ok) {
    throw new Error(String(response.status));
  }
  const data: unknown = await response.json();
  if (!validate(data)) {
    throw new InvalidPayloadError(url);
  }
  return data;
};
