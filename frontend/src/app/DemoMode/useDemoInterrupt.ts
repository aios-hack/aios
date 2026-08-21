import { useEffect, useRef } from 'react';

const EVENTS = ['pointerdown', 'keydown', 'wheel'] as const;

export const useDemoInterrupt = (
  enabled: boolean,
  onInterrupt: () => void,
  ignore: (target: EventTarget | null) => boolean
): void => {
  const handler = useRef({ onInterrupt, ignore });
  handler.current = { onInterrupt, ignore };

  useEffect(() => {
    if (!enabled) {
      return;
    }
    const listener = (event: Event) => {
      if (handler.current.ignore(event.target)) {
        return;
      }
      handler.current.onInterrupt();
    };
    for (const name of EVENTS) {
      window.addEventListener(name, listener, true);
    }
    return () => {
      for (const name of EVENTS) {
        window.removeEventListener(name, listener, true);
      }
    };
  }, [enabled]);
};
