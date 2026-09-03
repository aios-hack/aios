export interface SpeechAlternative {
  transcript: string;
}

export interface SpeechResult {
  isFinal: boolean;
  0: SpeechAlternative;
  length: number;
}

export interface SpeechResultList {
  length: number;
  [index: number]: SpeechResult;
}

export interface SpeechRecognitionEventLike {
  resultIndex: number;
  results: SpeechResultList;
}

export interface SpeechRecognitionLike {
  lang: string;
  continuous: boolean;
  interimResults: boolean;
  start: () => void;
  stop: () => void;
  abort: () => void;
  onresult: ((event: SpeechRecognitionEventLike) => void) | null;
  onend: (() => void) | null;
  onerror: (() => void) | null;
}

type RecognitionConstructor = new () => SpeechRecognitionLike;

interface SpeechWindow {
  SpeechRecognition?: RecognitionConstructor;
  webkitSpeechRecognition?: RecognitionConstructor;
}

export const recognitionConstructor = (): RecognitionConstructor | null => {
  if (typeof window === 'undefined') {
    return null;
  }
  const scope = window as unknown as SpeechWindow;
  return scope.SpeechRecognition ?? scope.webkitSpeechRecognition ?? null;
};

export const speechSupported = (): boolean => recognitionConstructor() !== null;

export const recognitionLang = (lang: string): string => (lang === 'en' ? 'en-US' : 'ru-RU');

export const collectTranscript = (
  event: SpeechRecognitionEventLike
): { text: string; final: boolean } => {
  let text = '';
  let final = false;
  for (let index = 0; index < event.results.length; index += 1) {
    const result = event.results[index];
    text += result[0].transcript;
    if (result.isFinal) {
      final = true;
    }
  }
  return { text: text.trim(), final };
};
