import { useEffect, useRef } from 'react';
import { speakingEnvelope } from '../sphere/sphereState';

export const MS_PER_CHARACTER = 62;
export const MIN_PHRASE_MS = 700;

export const phraseDurationMs = (text: string): number =>
  Math.max(MIN_PHRASE_MS, text.trim().length * MS_PER_CHARACTER);

export const speechSynthesisSupported = (): boolean =>
  typeof window !== 'undefined' && typeof window.speechSynthesis !== 'undefined';

export const speakLang = (lang: string): string => (lang === 'en' ? 'en-US' : 'ru-RU');

interface SpeakOptions {
  enabled: boolean;
  lang: string;
  text: string | null;
  onEnvelope: (level: number) => void;
}

export const useSpeak = ({ enabled, lang, text, onEnvelope }: SpeakOptions): void => {
  const handler = useRef(onEnvelope);
  handler.current = onEnvelope;

  useEffect(() => {
    if (!enabled || text === null || text.trim().length === 0) {
      return;
    }
    const total = phraseDurationMs(text);
    const start = performance.now();
    let raf = requestAnimationFrame(function tick(now: number) {
      const elapsed = now - start;
      handler.current(speakingEnvelope(elapsed, total));
      if (elapsed < total) {
        raf = requestAnimationFrame(tick);
        return;
      }
      handler.current(0);
    });

    if (speechSynthesisSupported()) {
      const utterance = new SpeechSynthesisUtterance(text);
      utterance.lang = speakLang(lang);
      window.speechSynthesis.cancel();
      window.speechSynthesis.speak(utterance);
    }

    return () => {
      cancelAnimationFrame(raf);
      handler.current(0);
      if (speechSynthesisSupported()) {
        window.speechSynthesis.cancel();
      }
    };
  }, [enabled, lang, text]);
};
