import { useCallback, useEffect, useRef, useState } from 'react';

interface PaletteState {
  open: boolean;
  query: string;
  active: number;
  setQuery: (query: string) => void;
  setActive: (index: number) => void;
  move: (delta: number, total: number) => void;
  openPalette: () => void;
  closePalette: () => void;
}

export const useCommandPalette = (): PaletteState => {
  const [open, setOpen] = useState(false);
  const [query, setQueryValue] = useState('');
  const [active, setActive] = useState(0);
  const opener = useRef<Element | null>(null);

  const openPalette = useCallback(() => {
    opener.current = document.activeElement;
    setQueryValue('');
    setActive(0);
    setOpen(true);
  }, []);

  const closePalette = useCallback(() => {
    setOpen(false);
    const node = opener.current;
    opener.current = null;
    if (node instanceof HTMLElement || node instanceof SVGElement) {
      node.focus();
    }
  }, []);

  const setQuery = useCallback((next: string) => {
    setQueryValue(next);
    setActive(0);
  }, []);

  const move = useCallback((delta: number, total: number) => {
    if (total === 0) {
      return;
    }
    setActive((current) => (current + delta + total) % total);
  }, []);

  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key !== 'k' && event.key !== 'K') {
        return;
      }
      if (!event.metaKey && !event.ctrlKey) {
        return;
      }
      event.preventDefault();
      if (open) {
        closePalette();
      } else {
        openPalette();
      }
    };
    window.addEventListener('keydown', onKeyDown);
    return () => window.removeEventListener('keydown', onKeyDown);
  }, [open, openPalette, closePalette]);

  return { open, query, active, setQuery, setActive, move, openPalette, closePalette };
};
