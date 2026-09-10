import { useEffect, useState } from 'react';
import { CONSOLE_OVERLAY_ID, consoleOverlayHost } from './overlayHost';

export const useOverlayHost = (): HTMLElement | null => {
  const [host, setHost] = useState<HTMLElement | null>(null);

  useEffect(() => {
    const resolve = () => setHost(consoleOverlayHost());
    resolve();
    const target = document.getElementById(CONSOLE_OVERLAY_ID);
    if (target !== null) {
      return;
    }
    const observer = new MutationObserver(() => {
      if (document.getElementById(CONSOLE_OVERLAY_ID) !== null) {
        resolve();
        observer.disconnect();
      }
    });
    observer.observe(document.body, { childList: true, subtree: true });
    return () => observer.disconnect();
  }, []);

  return host;
};
