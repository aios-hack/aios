import { readStored, writeStored } from '@/shared/lib/storage/storage';
export interface Transcript {
  text: string;
  final: boolean;
}

export const CONFIRM_KEY = 'aios-jarvis-confirm-voice';
export const SPEAK_KEY = 'aios-jarvis-speak';
export const EMPTY_TRANSCRIPT: Transcript = { text: '', final: false };

export const readFlag = (key: string, fallback: boolean): boolean => {
  const found = readStored(key);
  return found === null ? fallback : found === '1';
};

export const writeFlag = (key: string, value: boolean): void => {
  writeStored(key, value ? '1' : '0');
};
