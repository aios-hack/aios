import { useCallback, useRef, useState } from 'react';

export const TRANSCRIBE_URL = '/api/jarvis/transcribe';
export const MIME = 'audio/webm;codecs=opus';
export const BITS_PER_SECOND = 32000;
export const MAX_RECORD_MS = 25000;

export const recorderSupported = (): boolean =>
  typeof window !== 'undefined' &&
  typeof MediaRecorder === 'function' &&
  typeof navigator !== 'undefined' &&
  navigator.mediaDevices !== undefined;

export const readTranscript = (value: unknown): string => {
  if (typeof value !== 'object' || value === null) {
    return '';
  }
  const text = (value as Record<string, unknown>).text;
  return typeof text === 'string' ? text.trim() : '';
};

export const postAudio = async (
  blob: Blob,
  lang: string,
  fetchImpl?: typeof fetch
): Promise<string> => {
  const call = fetchImpl ?? fetch;
  try {
    const response = await call(TRANSCRIBE_URL, {
      method: 'POST',
      headers: { 'content-type': blob.type || MIME, 'X-Jarvis-Lang': lang },
      body: blob
    });
    if (!response.ok) {
      return '';
    }
    return readTranscript(await response.json());
  } catch {
    return '';
  }
};

interface RecorderOptions {
  lang: string;
  onText: (text: string) => void;
}

export interface Recorder {
  supported: boolean;
  recording: boolean;
  start: () => void;
  stop: () => void;
}

export const useRecorder = ({ lang, onText }: RecorderOptions): Recorder => {
  const [recording, setRecording] = useState(false);
  const media = useRef<MediaRecorder | null>(null);
  const stream = useRef<MediaStream | null>(null);
  const timer = useRef(0);
  const handler = useRef(onText);
  handler.current = onText;

  const release = useCallback(() => {
    window.clearTimeout(timer.current);
    stream.current?.getTracks().forEach((track) => track.stop());
    stream.current = null;
    media.current = null;
    setRecording(false);
  }, []);

  const stop = useCallback(() => {
    if (media.current !== null && media.current.state !== 'inactive') {
      media.current.stop();
      return;
    }
    release();
  }, [release]);

  const start = useCallback(() => {
    if (!recorderSupported() || media.current !== null) {
      return;
    }
    const run = async () => {
      let live: MediaStream;
      try {
        live = await navigator.mediaDevices.getUserMedia({ audio: true });
      } catch {
        return;
      }
      const supported =
        typeof MediaRecorder.isTypeSupported === 'function' && MediaRecorder.isTypeSupported(MIME);
      const recorder = new MediaRecorder(
        live,
        supported ? { mimeType: MIME, audioBitsPerSecond: BITS_PER_SECOND } : undefined
      );
      const chunks: Blob[] = [];
      recorder.ondataavailable = (event) => {
        if (event.data.size > 0) {
          chunks.push(event.data);
        }
      };
      recorder.onstop = () => {
        release();
        if (chunks.length === 0) {
          return;
        }
        const blob = new Blob(chunks, { type: recorder.mimeType || MIME });
        void postAudio(blob, lang).then((text) => {
          if (text.length > 0) {
            handler.current(text);
          }
        });
      };
      stream.current = live;
      media.current = recorder;
      setRecording(true);
      recorder.start();
      timer.current = window.setTimeout(() => stop(), MAX_RECORD_MS);
    };
    void run();
  }, [lang, release, stop]);

  return { supported: recorderSupported(), recording, start, stop };
};
