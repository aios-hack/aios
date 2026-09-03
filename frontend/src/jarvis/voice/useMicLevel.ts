import { useEffect, useRef } from 'react';

export const rmsOf = (samples: Float32Array): number => {
  if (samples.length === 0) {
    return 0;
  }
  let sum = 0;
  for (let index = 0; index < samples.length; index += 1) {
    sum += samples[index] * samples[index];
  }
  return Math.sqrt(sum / samples.length);
};

export const levelOf = (rms: number): number =>
  Math.min(1, Math.max(0, Math.sqrt(rms) * 2.4));

interface AudioWindow {
  AudioContext?: typeof AudioContext;
  webkitAudioContext?: typeof AudioContext;
}

const audioContextConstructor = (): typeof AudioContext | null => {
  if (typeof window === 'undefined') {
    return null;
  }
  const scope = window as unknown as AudioWindow;
  return scope.AudioContext ?? scope.webkitAudioContext ?? null;
};

export const useMicLevel = (active: boolean, onLevel: (level: number) => void): void => {
  const handler = useRef(onLevel);
  handler.current = onLevel;

  useEffect(() => {
    if (!active) {
      handler.current(0);
      return;
    }
    const Constructor = audioContextConstructor();
    if (
      Constructor === null ||
      typeof navigator === 'undefined' ||
      navigator.mediaDevices === undefined
    ) {
      return;
    }
    let context: AudioContext | null = null;
    let stream: MediaStream | null = null;
    let raf = 0;
    let stopped = false;

    const run = async () => {
      try {
        stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      } catch {
        return;
      }
      if (stopped) {
        stream.getTracks().forEach((track) => track.stop());
        return;
      }
      context = new Constructor();
      const source = context.createMediaStreamSource(stream);
      const analyser = context.createAnalyser();
      analyser.fftSize = 512;
      source.connect(analyser);
      const buffer = new Float32Array(analyser.fftSize);
      const tick = () => {
        analyser.getFloatTimeDomainData(buffer);
        handler.current(levelOf(rmsOf(buffer)));
        raf = requestAnimationFrame(tick);
      };
      raf = requestAnimationFrame(tick);
    };

    void run();

    return () => {
      stopped = true;
      if (raf !== 0) {
        cancelAnimationFrame(raf);
      }
      stream?.getTracks().forEach((track) => track.stop());
      void context?.close();
      handler.current(0);
    };
  }, [active]);
};
