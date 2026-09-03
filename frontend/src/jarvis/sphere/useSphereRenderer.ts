import { useEffect, useRef } from 'react';
import { createSphereProgram, setColor, setFloat } from './sphereProgram';
import {
  breathAt,
  breathPeriodOf,
  dprCap,
  energyOf,
  errorAt,
  haloScaleOf,
  pulseAt,
  pulseGapOf,
  readSpherePalette,
  type SpherePalette,
  type SphereState
} from './sphereState';

interface RendererOptions {
  state: SphereState;
  audio: number;
  burst: number;
  reducedMotion: boolean;
  onFallback: () => void;
}

interface Frame {
  start: number;
  pulseStart: number;
  pulseNext: number;
  errorStart: number;
  lastState: SphereState;
}

export const useSphereRenderer = (
  canvasRef: React.RefObject<HTMLCanvasElement | null>,
  { state, audio, burst, reducedMotion, onFallback }: RendererOptions
): void => {
  const live = useRef({ state, audio, burst, reducedMotion });
  live.current = { state, audio, burst, reducedMotion };

  useEffect(() => {
    const canvas = canvasRef.current;
    if (canvas === null) {
      return;
    }
    const created = createSphereProgram(canvas);
    if (created === null) {
      onFallback();
      return;
    }
    const { gl, program, uniforms, vao } = created;
    let palette: SpherePalette = readSpherePalette(document.documentElement);
    let visible = true;
    let onScreen = true;
    let raf = 0;
    const frame: Frame = {
      start: performance.now(),
      pulseStart: -Infinity,
      pulseNext: performance.now() + pulseGapOf('idle', Math.random()),
      errorStart: -Infinity,
      lastState: state
    };

    const resize = () => {
      const ratio = dprCap(window.devicePixelRatio ?? 1);
      const rect = canvas.getBoundingClientRect();
      const width = Math.max(1, Math.round(rect.width * ratio));
      const height = Math.max(1, Math.round(rect.height * ratio));
      if (canvas.width !== width || canvas.height !== height) {
        canvas.width = width;
        canvas.height = height;
        gl.viewport(0, 0, width, height);
      }
    };

    const draw = (now: number) => {
      const current = live.current;
      if (current.state !== frame.lastState) {
        if (current.state === 'error') {
          frame.errorStart = now;
        }
        frame.lastState = current.state;
      }
      if (now >= frame.pulseNext) {
        frame.pulseStart = now;
        frame.pulseNext = now + pulseGapOf(current.state, Math.random());
      }
      resize();
      gl.useProgram(program);
      gl.bindVertexArray(vao);
      gl.enable(gl.BLEND);
      gl.blendFunc(gl.SRC_ALPHA, gl.ONE_MINUS_SRC_ALPHA);
      gl.clearColor(0, 0, 0, 0);
      gl.clear(gl.COLOR_BUFFER_BIT);
      const elapsed = current.reducedMotion ? 0 : now - frame.start;
      const breath = current.reducedMotion
        ? 0.5
        : breathAt(elapsed, breathPeriodOf(current.state));
      setFloat(gl, uniforms.u_time, elapsed / 1000);
      setFloat(gl, uniforms.u_breath, breath);
      setFloat(
        gl,
        uniforms.u_pulse,
        current.reducedMotion ? 0 : pulseAt(now - frame.pulseStart)
      );
      setFloat(gl, uniforms.u_energy, energyOf(current.state));
      setFloat(gl, uniforms.u_audio, Math.min(Math.max(current.audio, 0), 1));
      setFloat(gl, uniforms.u_burst, Math.min(Math.max(current.burst, 0), 1));
      setFloat(
        gl,
        uniforms.u_error,
        current.reducedMotion
          ? current.state === 'error'
            ? 1
            : 0
          : errorAt(now - frame.errorStart)
      );
      setFloat(
        gl,
        uniforms.u_halo,
        palette['--color-jarvis-halo'].a * haloScaleOf(current.state) * 3.2
      );
      setColor(gl, uniforms.u_body, palette['--color-jarvis-body']);
      setColor(gl, uniforms.u_pulseColor, palette['--color-jarvis-pulse']);
      setColor(gl, uniforms.u_deep, palette['--color-jarvis-deep']);
      setColor(gl, uniforms.u_rim, palette['--color-jarvis-rim']);
      setColor(gl, uniforms.u_spark, palette['--color-jarvis-spark']);
      gl.drawArrays(gl.TRIANGLES, 0, 3);
      gl.bindVertexArray(null);
    };

    const loop = (now: number) => {
      draw(now);
      raf = visible && onScreen ? requestAnimationFrame(loop) : 0;
    };

    const restart = () => {
      if (raf === 0 && visible && onScreen) {
        raf = requestAnimationFrame(loop);
      }
    };

    const onVisibility = () => {
      visible = document.visibilityState !== 'hidden';
      restart();
    };

    const themeObserver =
      typeof MutationObserver === 'function'
        ? new MutationObserver(() => {
            palette = readSpherePalette(document.documentElement);
          })
        : null;
    themeObserver?.observe(document.documentElement, {
      attributes: true,
      attributeFilter: ['data-theme']
    });

    const intersection =
      typeof IntersectionObserver === 'function'
        ? new IntersectionObserver((entries) => {
            onScreen = entries.some((entry) => entry.isIntersecting);
            restart();
          })
        : null;
    intersection?.observe(canvas);

    const resizeObserver =
      typeof ResizeObserver === 'function' ? new ResizeObserver(() => resize()) : null;
    resizeObserver?.observe(canvas);

    document.addEventListener('visibilitychange', onVisibility);
    raf = requestAnimationFrame(loop);

    return () => {
      if (raf !== 0) {
        cancelAnimationFrame(raf);
      }
      document.removeEventListener('visibilitychange', onVisibility);
      themeObserver?.disconnect();
      intersection?.disconnect();
      resizeObserver?.disconnect();
      gl.deleteProgram(program);
    };
  }, [canvasRef, onFallback]);
};
