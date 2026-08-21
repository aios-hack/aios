import { fetchJson } from './fetchJson';

const pending = new Map<string, Promise<unknown>>();
const settled = new Map<string, unknown>();

export const readCachedJson = <T,>(
  url: string,
  validate: (data: unknown) => data is T
): T | null => {
  const data = settled.get(url);
  return data !== undefined && validate(data) ? data : null;
};

export const loadJson = <T,>(
  url: string,
  validate: (data: unknown) => data is T
): Promise<T> => {
  const inFlight = pending.get(url);
  if (inFlight !== undefined) {
    return inFlight as Promise<T>;
  }
  const request = fetchJson(url, validate)
    .then((data) => {
      settled.set(url, data);
      pending.delete(url);
      return data;
    })
    .catch((error: unknown) => {
      pending.delete(url);
      throw error;
    });
  pending.set(url, request);
  return request as Promise<T>;
};

export const clearJsonCache = (): void => {
  pending.clear();
  settled.clear();
};
