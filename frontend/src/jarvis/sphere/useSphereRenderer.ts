import { useEffect, useRef } from 'react';
import {
  applyBlend,
  createSphereProgram,
  setColor,
  setFloat,
  setVec2,
  setVec4Array
} from './sphereProgram';
import { emptyBolts, packBolts, stepBolts, type BoltField } from './sphereBolts';
import {
  SMOOTH_TAU_MS,
  approach,
  breathOfPhase,
  breathPeriodOf,
  dprCap,
  energyOf,
  errorAt,
  flowSpeedOf,
  haloScaleOf,
  readSpherePalette,
  spinSpeedOf,
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

interface Phase {
  spin: number;
  flow: number;
  breath: number;
}

const MAX_FRAME_MS = 64;
const BREATH_VAR = '--jarvis-breath';

const isLightTheme = (): boolean =>
  typeof document !== 'undefined' &&
  document.documentElement.getAttribute('data-theme') === 'light';

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
    let light = isLightTheme();
    let visible = true;
    let onScreen = true;
    let raf = 0;
    let last = performance.now();
    let errorStart = -Infinity;
    let lastState: SphereState = state;
    let energy = energyOf(state);
    let halo = haloScaleOf(state);
    let pointer: [number, number] = [0, 0];
    const phase: Phase = { spin: 0, flow: 0, breath: 0 };
    const bolts: BoltField = emptyBolts(last);

    const onPointerMove = (event: PointerEvent) => {
      const rect = canvas.getBoundingClientRect();
      if (rect.width <= 0 || rect.height <= 0) {
        return;
      }
      pointer = [
        ((event.clientX - rect.left) / rect.width) * 2 - 1,
        1 - ((event.clientY - rect.top) / rect.height) * 2
      ];
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
      const dt = Math.min(Math.max(now - last, 0), MAX_FRAME_MS);
      last = now;
      if (current.state !== lastState) {
        if (current.state === 'error') {
          errorStart = now;
        }
        lastState = current.state;
      }
      const still = current.reducedMotion;
      const targetEnergy = energyOf(current.state);
      const targetHalo = haloScaleOf(current.state);
      energy = still ? targetEnergy : approach(energy, targetEnergy, dt, SMOOTH_TAU_MS);
      halo = still ? targetHalo : approach(halo, targetHalo, dt, SMOOTH_TAU_MS);
      const audioLevel = Math.min(Math.max(current.audio, 0), 1);
      if (!still) {
        const seconds = dt / 1000;
        phase.spin += seconds * spinSpeedOf(energy);
        phase.flow += seconds * flowSpeedOf(energy);
        phase.breath += dt / breathPeriodOf(current.state);
        stepBolts(bolts, current.state, audioLevel, now);
      }
      const breath = still ? 0.5 : breathOfPhase(phase.breath);
      const written = breath.toFixed(3);
      canvas.style.setProperty(BREATH_VAR, written);
      document.documentElement.style.setProperty(BREATH_VAR, written);
      resize();
      gl.useProgram(program);
      gl.bindVertexArray(vao);
      applyBlend(gl, light);
      gl.clearColor(0, 0, 0, 0);
      gl.clear(gl.COLOR_BUFFER_BIT);
      setFloat(gl, uniforms.u_spin, phase.spin);
      setFloat(gl, uniforms.u_flow, phase.flow);
      setFloat(gl, uniforms.u_breath, breath);
      setFloat(gl, uniforms.u_energy, energy);
      setFloat(gl, uniforms.u_audio, audioLevel);
      setFloat(gl, uniforms.u_burst, Math.min(Math.max(current.burst, 0), 1));
      setFloat(gl, uniforms.u_theme, light ? 1 : 0);
      setFloat(gl, uniforms.u_pixel, 2 / Math.max(canvas.width, 1));
      setFloat(
        gl,
        uniforms.u_error,
        still ? (current.state === 'error' ? 1 : 0) : errorAt(now - errorStart)
      );
      setFloat(gl, uniforms.u_halo, palette['--color-jarvis-halo'].a * halo * 3.2);
      setVec2(gl, uniforms.u_pointer, pointer[0], pointer[1]);
      setVec4Array(gl, uniforms.u_bolts, still ? new Float32Array(16) : packBolts(bolts, now));
      setColor(gl, uniforms.u_body, palette['--color-jarvis-body']);
      setColor(gl, uniforms.u_pulseColor, palette['--color-jarvis-pulse']);
      setColor(gl, uniforms.u_deep, palette['--color-jarvis-deep']);
      setColor(gl, uniforms.u_rim, palette['--color-jarvis-rim']);
      setColor(gl, uniforms.u_spark, palette['--color-jarvis-spark']);
      setColor(gl, uniforms.u_shadow, palette['--color-jarvis-shadow']);
      gl.drawArrays(gl.TRIANGLES, 0, 3);
      gl.bindVertexArray(null);
    };

    const loop = (now: number) => {
      draw(now);
      raf = visible && onScreen ? requestAnimationFrame(loop) : 0;
    };

    const restart = () => {
      if (raf === 0 && visible && onScreen) {
        last = performance.now();
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
            light = isLightTheme();
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
    window.addEventListener('pointermove', onPointerMove, { passive: true });
    raf = requestAnimationFrame(loop);

    return () => {
      if (raf !== 0) {
        cancelAnimationFrame(raf);
      }
      document.removeEventListener('visibilitychange', onVisibility);
      window.removeEventListener('pointermove', onPointerMove);
      themeObserver?.disconnect();
      intersection?.disconnect();
      resizeObserver?.disconnect();
      gl.deleteProgram(program);
    };
  }, [canvasRef, onFallback]);
};
