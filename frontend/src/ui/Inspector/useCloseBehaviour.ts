import { useEffect, useRef } from 'react';

export const useCloseBehaviour = (open: boolean, onClose: () => void): void => {
  const openerRef = useRef<Element | null>(null);

  useEffect(() => {
    if (!open) {
      return;
    }
    if (openerRef.current === null) {
      openerRef.current = document.activeElement;
    }
    return () => {
      const opener = openerRef.current;
      openerRef.current = null;
      if (opener instanceof Element && document.contains(opener)) {
        (opener as HTMLElement | SVGElement).focus();
      }
    };
  }, [open]);

  useEffect(() => {
    if (!open) {
      return;
    }
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        onClose();
      }
    };
    window.addEventListener('keydown', onKeyDown);
    return () => window.removeEventListener('keydown', onKeyDown);
  }, [open, onClose]);
};
