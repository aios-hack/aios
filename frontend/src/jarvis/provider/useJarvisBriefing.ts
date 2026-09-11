import { useEffect, useRef } from 'react';
import { fetchBriefing, fetchSessionEvents } from '@/jarvis/model/sessions';
import type { JarvisEvent } from '@/jarvis/transport/events';

interface BriefingOptions {
  open: boolean;
  sessionId: string;
  sceneCount: number;
  lang: string;
  scenario: string;
  step: number;
  pushEvents: (events: readonly JarvisEvent[]) => void;
}

export const useJarvisBriefing = ({
  open,
  sessionId,
  sceneCount,
  lang,
  scenario,
  step,
  pushEvents
}: BriefingOptions): void => {
  const done = useRef(false);

  useEffect(() => {
    if (!open || done.current || sceneCount > 0) {
      return;
    }
    done.current = true;
    const start = async () => {
      const stored = await fetchSessionEvents(sessionId);
      if (stored.length > 0) {
        pushEvents(stored);
        return;
      }
      const events = await fetchBriefing(sessionId, lang, scenario, step);
      if (events.length > 0) {
        pushEvents(events);
      }
    };
    void start();
  }, [open, sessionId, sceneCount, lang, scenario, step, pushEvents]);
};
