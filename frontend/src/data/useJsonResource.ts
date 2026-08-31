import { useEffect, useRef, useState } from 'react';
import { loadJson, readCachedJson } from './jsonCache';
import type { ResourceState } from './ResourceState';

const initialStateFor = <T,>(
  url: string | null,
  validate: (data: unknown) => data is T
): ResourceState<T> => {
  if (url === null) {
    return { status: 'loading' };
  }
  const cached = readCachedJson(url, validate);
  return cached === null ? { status: 'loading' } : { status: 'ready', data: cached };
};

export const useJsonResource = <T,>(
  url: string | null,
  validate: (data: unknown) => data is T
): ResourceState<T> => {
  const [state, setState] = useState<ResourceState<T>>(() => initialStateFor(url, validate));
  const validateRef = useRef(validate);
  validateRef.current = validate;

  useEffect(() => {
    if (url === null) {
      setState({ status: 'loading' });
      return;
    }
    let cancelled = false;
    const check = validateRef.current;
    const cached = readCachedJson(url, check);
    if (cached !== null) {
      setState({ status: 'ready', data: cached });
      return;
    }
    setState({ status: 'loading' });
    loadJson(url, check)
      .then((data) => {
        if (!cancelled) {
          setState({ status: 'ready', data });
        }
      })
      .catch(() => {
        if (!cancelled) {
          setState({ status: 'error' });
        }
      });
    return () => {
      cancelled = true;
    };
  }, [url]);

  return state;
};
