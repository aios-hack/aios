import { SPHERE_FRAGMENT, SPHERE_VERTEX } from './sphere.frag';

const UNIFORMS = [
  'u_time',
  'u_pulse',
  'u_energy',
  'u_audio',
  'u_breath',
  'u_error',
  'u_burst',
  'u_body',
  'u_pulseColor',
  'u_deep',
  'u_rim',
  'u_spark',
  'u_halo'
] as const;

export type UniformName = (typeof UNIFORMS)[number];
export type UniformMap = Partial<Record<UniformName, WebGLUniformLocation | null>>;

export interface SphereProgram {
  gl: WebGL2RenderingContext;
  program: WebGLProgram;
  uniforms: UniformMap;
  vao: WebGLVertexArrayObject | null;
}

const compile = (
  gl: WebGL2RenderingContext,
  kind: number,
  source: string
): WebGLShader | null => {
  const shader = gl.createShader(kind);
  if (shader === null) {
    return null;
  }
  gl.shaderSource(shader, source);
  gl.compileShader(shader);
  if (gl.getShaderParameter(shader, gl.COMPILE_STATUS) !== true) {
    gl.deleteShader(shader);
    return null;
  }
  return shader;
};

const usable = (gl: unknown): gl is WebGL2RenderingContext =>
  gl !== null &&
  typeof gl === 'object' &&
  typeof (gl as WebGL2RenderingContext).createShader === 'function' &&
  typeof (gl as WebGL2RenderingContext).createVertexArray === 'function';

export const createSphereProgram = (canvas: HTMLCanvasElement): SphereProgram | null => {
  let raw: unknown = null;
  try {
    raw = canvas.getContext('webgl2', {
      alpha: true,
      antialias: false,
      premultipliedAlpha: false,
      powerPreference: 'low-power'
    });
  } catch {
    return null;
  }
  if (!usable(raw)) {
    return null;
  }
  const gl = raw;
  const vertex = compile(gl, gl.VERTEX_SHADER, SPHERE_VERTEX);
  const fragment = compile(gl, gl.FRAGMENT_SHADER, SPHERE_FRAGMENT);
  const program = gl.createProgram();
  if (vertex === null || fragment === null || program === null) {
    return null;
  }
  gl.attachShader(program, vertex);
  gl.attachShader(program, fragment);
  gl.linkProgram(program);
  gl.deleteShader(vertex);
  gl.deleteShader(fragment);
  if (gl.getProgramParameter(program, gl.LINK_STATUS) !== true) {
    gl.deleteProgram(program);
    return null;
  }
  const vao = gl.createVertexArray();
  gl.bindVertexArray(vao);
  const buffer = gl.createBuffer();
  gl.bindBuffer(gl.ARRAY_BUFFER, buffer);
  gl.bufferData(gl.ARRAY_BUFFER, new Float32Array([-1, -1, 3, -1, -1, 3]), gl.STATIC_DRAW);
  const location = gl.getAttribLocation(program, 'a_position');
  gl.enableVertexAttribArray(location);
  gl.vertexAttribPointer(location, 2, gl.FLOAT, false, 0, 0);
  gl.bindVertexArray(null);
  const uniforms: UniformMap = {};
  for (const name of UNIFORMS) {
    uniforms[name] = gl.getUniformLocation(program, name);
  }
  return { gl, program, uniforms, vao };
};

export const setColor = (
  gl: WebGL2RenderingContext,
  location: WebGLUniformLocation | null | undefined,
  color: { r: number; g: number; b: number }
): void => {
  if (location === null || location === undefined) {
    return;
  }
  gl.uniform3f(location, color.r / 255, color.g / 255, color.b / 255);
};

export const setFloat = (
  gl: WebGL2RenderingContext,
  location: WebGLUniformLocation | null | undefined,
  value: number
): void => {
  if (location === null || location === undefined) {
    return;
  }
  gl.uniform1f(location, value);
};
