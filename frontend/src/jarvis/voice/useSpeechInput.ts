import { useCallback, useEffect, useRef, useState } from 'react';
import { useI18n } from '../../i18n/I18nContext';
import {
  collectTranscript,
  recognitionConstructor,
  recognitionLang,
  speechSupported,
  type SpeechRecognitionLike
} from './speechTypes';

export const SILENCE_RMS = 0.06;
export const SILENCE_MS = 900;

interface SpeechInput {
  supported: boolean;
  listening: boolean;
  start: () => void;
  stop: () => void;
  error: string | null;
  noteLevel: (level: number) => void;
}

interface SpeechOptions {
  onInterim: (text: string) => void;
  onFinal: (text: string) => void;
  onFailure: (code: string) => void;
}

export const useSpeechInput = ({
  onInterim,
  onFinal,
  onFailure
}: SpeechOptions): SpeechInput => {
  const { lang } = useI18n();
  const [listening, setListening] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const recognition = useRef<SpeechRecognitionLike | null>(null);
  const best = useRef('');
  const quietSince = useRef(0);
  const handlers = useRef({ onInterim, onFinal, onFailure });
  handlers.current = { onInterim, onFinal, onFailure };

  useEffect(
    () => () => {
      recognition.current?.abort();
      recognition.current = null;
    },
    []
  );

  const stop = useCallback(() => {
    recognition.current?.stop();
  }, []);

  const noteLevel = useCallback(
    (level: number) => {
      if (recognition.current === null) {
        quietSince.current = 0;
        return;
      }
      if (level > SILENCE_RMS) {
        quietSince.current = 0;
        return;
      }
      if (best.current.length === 0) {
        return;
      }
      const now = performance.now();
      if (quietSince.current === 0) {
        quietSince.current = now;
        return;
      }
      if (now - quietSince.current > SILENCE_MS) {
        quietSince.current = 0;
        stop();
      }
    },
    [stop]
  );

  const start = useCallback(() => {
    const Constructor = recognitionConstructor();
    if (Constructor === null || recognition.current !== null) {
      return;
    }
    const instance = new Constructor();
    instance.lang = recognitionLang(lang);
    instance.continuous = true;
    instance.interimResults = true;
    best.current = '';
    quietSince.current = 0;
    setError(null);
    instance.onresult = (event) => {
      const { text, final } = collectTranscript(event);
      if (text.length === 0) {
        return;
      }
      best.current = text;
      if (final) {
        handlers.current.onFinal(text);
        return;
      }
      handlers.current.onInterim(text);
    };
    instance.onend = () => {
      const collected = best.current;
      recognition.current = null;
      setListening(false);
      if (collected.length > 0) {
        best.current = '';
        handlers.current.onFinal(collected);
      }
    };
    instance.onerror = (event) => {
      const code = typeof event?.error === 'string' ? event.error : 'unknown';
      recognition.current = null;
      setListening(false);
      if (code !== 'no-speech' && code !== 'aborted') {
        setError(code);
        handlers.current.onFailure(code);
      }
    };
    recognition.current = instance;
    setListening(true);
    instance.start();
  }, [lang]);

  return { supported: speechSupported(), listening, start, stop, error, noteLevel };
};
