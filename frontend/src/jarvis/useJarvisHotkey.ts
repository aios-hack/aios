import { useEffect } from 'react';
import { isEditableTarget } from '../app/useHotkeys';

export const JARVIS_KEY = 'j';

export const useJarvisHotkey = (enabled: boolean, onOpen: () => void): void => {
  useEffect(() => {
    if (!enabled) {
      return;
    }
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.defaultPrevented || event.metaKey || event.ctrlKey || event.altKey) {
        return;
      }
      if (event.key.toLowerCase() !== JARVIS_KEY || isEditableTarget(event.target)) {
        return;
      }
      event.preventDefault();
      onOpen();
    };
    window.addEventListener('keydown', onKeyDown);
    return () => window.removeEventListener('keydown', onKeyDown);
  }, [enabled, onOpen]);
};
