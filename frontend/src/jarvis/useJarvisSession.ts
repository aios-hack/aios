import { useCallback, useMemo, useRef, useState } from 'react';
import {
  adoptScene,
  emptyScenes,
  scenesReducer,
  selectSceneAt,
  type ScenesState
} from './scenes';
import {
  fetchSessionEvents,
  rememberSessionId,
  replayEvents,
  storedSessionId
} from './sessions';
import { QUESTION_LIMIT, type JarvisTransport } from './transport/JarvisTransport';
import type { JarvisAskContext, JarvisEvent } from './transport/events';

export interface JarvisSession {
  scenes: ScenesState;
  sessionId: string;
  askQuestion: (question: string) => void;
  pushEvents: (events: readonly JarvisEvent[]) => void;
  loadSession: (id: string) => void;
  startSession: () => void;
  cancel: () => void;
  selectScene: (index: number) => void;
  busy: boolean;
}

const localStore = (): Storage | null =>
  typeof localStorage === 'undefined' ? null : localStorage;

export const useJarvisSession = (
  transport: JarvisTransport,
  lang: string,
  askContext: JarvisAskContext
): JarvisSession => {
  const [scenes, setScenes] = useState<ScenesState>(emptyScenes);
  const [busy, setBusy] = useState(false);
  const abortRef = useRef<AbortController | null>(null);
  const [sessionId, setSessionId] = useState(() => storedSessionId(localStore()));
  const current = useRef(sessionId);
  current.current = sessionId;

  const cancel = useCallback(() => {
    abortRef.current?.abort();
    abortRef.current = null;
    setBusy(false);
  }, []);

  const selectScene = useCallback(
    (index: number) => setScenes((state) => selectSceneAt(state, index)),
    []
  );

  const pushEvents = useCallback((events: readonly JarvisEvent[]) => {
    abortRef.current?.abort();
    abortRef.current = null;
    setBusy(false);
    setScenes((state) => events.reduce((next, event) => scenesReducer(next, event), state));
  }, []);

  const loadSession = useCallback(
    (id: string) => {
      abortRef.current?.abort();
      abortRef.current = null;
      setBusy(false);
      setSessionId(id);
      rememberSessionId(localStore(), id);
      void fetchSessionEvents(id).then((events) => {
        if (current.current !== id) {
          return;
        }
        setScenes(replayEvents(events));
      });
    },
    []
  );

  const startSession = useCallback(() => {
    abortRef.current?.abort();
    abortRef.current = null;
    setBusy(false);
    const next = storedSessionId(null);
    setSessionId(next);
    rememberSessionId(localStore(), next);
    setScenes(emptyScenes);
  }, []);

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
      const pending = `pending-${Date.now()}`;
      setScenes((state) =>
        scenesReducer(state, {
          type: 'scene',
          scene_id: pending,
          question: text,
          context: askContext
        })
      );
      const run = async () => {
        try {
          for await (const event of transport.ask(
            { sessionId: current.current, question: text, lang, context: askContext },
            controller.signal
          )) {
            if (controller.signal.aborted) {
              return;
            }
            if (event.type === 'scene') {
              setScenes((state) => adoptScene(state, pending, event));
              continue;
            }
            setScenes((state) => scenesReducer(state, event));
          }
        } catch {
          if (!controller.signal.aborted) {
            setScenes((state) =>
              scenesReducer(state, {
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
    () => ({
      scenes,
      sessionId,
      askQuestion,
      pushEvents,
      loadSession,
      startSession,
      cancel,
      selectScene,
      busy
    }),
    [
      scenes,
      sessionId,
      askQuestion,
      pushEvents,
      loadSession,
      startSession,
      cancel,
      selectScene,
      busy
    ]
  );
};
