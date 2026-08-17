import { useEffect, useState } from 'react';
import { fetchJson } from './fetchJson';
import type { ResourceState } from './ResourceState';

export const useJsonResource = <T,>(
  url: string | null,
  validate: (data: unknown) => data is T
): ResourceState<T> => {
  const [state, setState] = useState<ResourceState<T>>({ status: 'loading' });

  useEffect(() => {
    if (url === null) {
      setState({ status: 'loading' });
      return;
    }
    let cancelled = false;
    setState({ status: 'loading' });
    fetchJson(url, validate)
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
