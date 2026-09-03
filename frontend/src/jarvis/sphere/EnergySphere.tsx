import { useCallback, useEffect, useRef, useState } from 'react';
import { useSphereRenderer } from './useSphereRenderer';
import type { SphereState } from './sphereState';
import './EnergySphere.css';
import './sphereFallback.css';

interface EnergySphereProps {
  state: SphereState;
  audio?: number;
  burst?: number;
  label?: string;
}

const prefersReducedMotion = (): boolean =>
  typeof window !== 'undefined' &&
  typeof window.matchMedia === 'function' &&
  window.matchMedia('(prefers-reduced-motion: reduce)').matches;

export const EnergySphere = ({ state, audio = 0, burst = 0, label }: EnergySphereProps) => {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const [fallback, setFallback] = useState(false);
  const [reduced, setReduced] = useState(prefersReducedMotion);

  useEffect(() => {
    if (typeof window === 'undefined' || typeof window.matchMedia !== 'function') {
      return;
    }
    const query = window.matchMedia('(prefers-reduced-motion: reduce)');
    const sync = () => setReduced(query.matches);
    sync();
    query.addEventListener('change', sync);
    return () => query.removeEventListener('change', sync);
  }, []);

  const onFallback = useCallback(() => setFallback(true), []);
  useSphereRenderer(canvasRef, { state, audio, burst, reducedMotion: reduced, onFallback });

  return (
    <span
      className="jarvis-sphere"
      data-state={state}
      data-fallback={fallback ? 'true' : undefined}
      role={label === undefined ? 'presentation' : 'img'}
      aria-label={label}
      aria-hidden={label === undefined ? true : undefined}
    >
      {fallback ? (
        <span className="jarvis-sphere-css" aria-hidden="true">
          <span className="jarvis-sphere-css-core" />
        </span>
      ) : (
        <canvas ref={canvasRef} className="jarvis-sphere-canvas" />
      )}
    </span>
  );
};
