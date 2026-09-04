import { useCallback, useMemo, useRef, useState } from 'react';
import {
  emptyScenes,
  scenesReducer,
  selectSceneAt,
  type ScenesState
} from './scenes';
import { QUESTION_LIMIT, sessionIdOf, type JarvisTransport } from './transport/JarvisTransport';
import type { JarvisAskContext, JarvisEvent } from './transport/events';

export interface JarvisSession {
  scenes: ScenesState;
  askQuestion: (question: string) => void;
  pushEvents: (events: readonly JarvisEvent[]) => void;
  cancel: () => void;
  selectScene: (index: number) => void;
  busy: boolean;
}

export const useJarvisSession = (
  transport: JarvisTransport,
  lang: string,
  askContext: JarvisAskContext
): JarvisSession => {
  const [scenes, setScenes] = useState<ScenesState>(emptyScenes);
  const [busy, setBusy] = useState(false);
  const abortRef = useRef<AbortController | null>(null);
  const sessionId = useRef(
    sessionIdOf(typeof sessionStorage === 'undefined' ? null : sessionStorage)
  );

  const cancel = useCallback(() => {
    abortRef.current?.abort();
    abortRef.current = null;
    setBusy(false);
  }, []);

  const selectScene = useCallback(
    (index: number) => setScenes((current) => selectSceneAt(current, index)),
    []
  );

  const pushEvents = useCallback(
    (events: readonly JarvisEvent[]) => {
      abortRef.current?.abort();
      abortRef.current = null;
      setBusy(false);
      setScenes((current) =>
        events.reduce((state, event) => scenesReducer(state, event), current)
      );
    },
    []
  );

  const askQuestion = useCallback(
    (question: string) => {
      const text = question.trim().slice(0, QUESTION_LIMIT);
      if (text.length === 0) {
        return;
      }
      abortRef.current?.abort();
      const controller = new AbortController();
      abortRef.current = controller;
      setBusy(true);
      const run = async () => {
        try {
          for await (const event of transport.ask(
            { sessionId: sessionId.current, question: text, lang, context: askContext },
            controller.signal
          )) {
            if (controller.signal.aborted) {
              return;
            }
            setScenes((current) => scenesReducer(current, event));
          }
        } catch {
          if (!controller.signal.aborted) {
            setScenes((current) =>
              scenesReducer(current, {
                type: 'error',
                code: 'upstream',
                message: 'transport threw'
              })
            );
          }
        } finally {
          if (abortRef.current === controller) {
            abortRef.current = null;
            setBusy(false);
          }
        }
      };
      void run();
    },
    [transport, askContext, lang]
  );

  return useMemo(
    () => ({ scenes, askQuestion, pushEvents, cancel, selectScene, busy }),
    [scenes, askQuestion, pushEvents, cancel, selectScene, busy]
  );
};
