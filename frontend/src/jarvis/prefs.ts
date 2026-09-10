export interface Transcript {
  text: string;
  final: boolean;
}

export const CONFIRM_KEY = 'aios-jarvis-confirm-voice';
export const SPEAK_KEY = 'aios-jarvis-speak';
export const EMPTY_TRANSCRIPT: Transcript = { text: '', final: false };

export const readFlag = (key: string, fallback: boolean): boolean => {
  if (typeof localStorage === 'undefined') {
    return fallback;
  }
  try {
    const found = localStorage.getItem(key);
    return found === null ? fallback : found === '1';
  } catch {
    return fallback;
  }
};

export const writeFlag = (key: string, value: boolean): void => {
  if (typeof localStorage === 'undefined') {
    return;
  }
  try {
    localStorage.setItem(key, value ? '1' : '0');
  } catch {
    return;
  }
};
