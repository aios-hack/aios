import { useCallback, useEffect, useRef, useState } from 'react';
import { useI18n } from '../../i18n/I18nContext';
import {
  collectTranscript,
  recognitionConstructor,
  recognitionLang,
  speechSupported,
  type SpeechRecognitionLike
} from './speechTypes';

interface SpeechInput {
  supported: boolean;
  listening: boolean;
  start: () => void;
  stop: () => void;
}

interface SpeechOptions {
  onInterim: (text: string) => void;
  onFinal: (text: string) => void;
}

export const useSpeechInput = ({ onInterim, onFinal }: SpeechOptions): SpeechInput => {
  const { lang } = useI18n();
  const [listening, setListening] = useState(false);
  const recognition = useRef<SpeechRecognitionLike | null>(null);
  const handlers = useRef({ onInterim, onFinal });
  handlers.current = { onInterim, onFinal };

  useEffect(
    () => () => {
      recognition.current?.abort();
      recognition.current = null;
    },
    []
  );

  const start = useCallback(() => {
    const Constructor = recognitionConstructor();
    if (Constructor === null || recognition.current !== null) {
      return;
    }
    const instance = new Constructor();
    instance.lang = recognitionLang(lang);
    instance.continuous = false;
    instance.interimResults = true;
    instance.onresult = (event) => {
      const { text, final } = collectTranscript(event);
      if (text.length === 0) {
        return;
      }
      if (final) {
        handlers.current.onFinal(text);
        return;
      }
      handlers.current.onInterim(text);
    };
    instance.onend = () => {
      recognition.current = null;
      setListening(false);
    };
    instance.onerror = () => {
      recognition.current = null;
      setListening(false);
    };
    recognition.current = instance;
    setListening(true);
    instance.start();
  }, [lang]);

  const stop = useCallback(() => {
    recognition.current?.stop();
  }, []);

  return { supported: speechSupported(), listening, start, stop };
};
