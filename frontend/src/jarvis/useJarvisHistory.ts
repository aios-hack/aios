import { useEffect } from 'react';
import type { TransitionState } from './transition';

export const HISTORY_FLAG = 'jarvis';

export const historyFlagged = (search: string): boolean =>
  new URLSearchParams(search).has(HISTORY_FLAG);

export const nextHistoryUrl = (
  pathname: string,
  search: string,
  flagged: boolean
): string => {
  const params = new URLSearchParams(search);
  if (flagged) {
    params.set(HISTORY_FLAG, '1');
  } else {
    params.delete(HISTORY_FLAG);
  }
  const query = params.toString();
  return query.length === 0 ? pathname : `${pathname}?${query}`;
};

export const shouldFlagHistory = (transition: TransitionState): boolean =>
  transition.direction === 'opening' || transition.phase === 'open';

export const useJarvisHistory = (
  transition: TransitionState,
  onPop: (flagged: boolean) => void
): void => {
  useEffect(() => {
    if (typeof window === 'undefined') {
      return;
    }
    const listener = () => onPop(historyFlagged(window.location.search));
    window.addEventListener('popstate', listener);
    return () => window.removeEventListener('popstate', listener);
  }, [onPop]);

  useEffect(() => {
    if (typeof window === 'undefined') {
      return;
    }
    const flagged = historyFlagged(window.location.search);
    const target = shouldFlagHistory(transition);
    if (target === flagged) {
      return;
    }
    const url = nextHistoryUrl(window.location.pathname, window.location.search, target);
    if (target) {
      window.history.pushState(null, '', url);
      return;
    }
    window.history.replaceState(null, '', url);
  }, [transition]);
};
