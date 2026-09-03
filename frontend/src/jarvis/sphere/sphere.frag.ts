import { SPHERE_NOISE } from './sphereNoise.glsl';

export const SPHERE_VERTEX = `#version 300 es
in vec2 a_position;
out vec2 v_uv;
void main() {
  v_uv = a_position;
  gl_Position = vec4(a_position, 0.0, 1.0);
}
`;

export const SPHERE_FRAGMENT = `#version 300 es
precision highp float;

in vec2 v_uv;
out vec4 outColor;

uniform float u_time;
uniform float u_pulse;
uniform float u_energy;
uniform float u_audio;
uniform float u_breath;
uniform float u_error;
uniform float u_burst;
uniform vec3 u_body;
uniform vec3 u_pulseColor;
uniform vec3 u_deep;
uniform vec3 u_rim;
uniform vec3 u_spark;
uniform float u_halo;

${SPHERE_NOISE}

const int LAYERS = 5;
const float SHELL = 0.86;

float ringMask(vec2 uv, float radius) {
  vec2 q = vec2(uv.x, (uv.y + 0.86) * 6.5);
  float d = abs(length(q) - radius);
  float band = 1.0 - smoothstep(0.0, 0.09, d);
  float angle = atan(q.y, q.x);
  float gaps = smoothstep(0.2, 0.9, abs(sin(angle * 3.0)));
  return band * mix(0.2, 1.0, gaps);
}

float waveAt(float depth, float phase) {
  float front = phase * 1.25;
  return exp(-pow((depth - front) * 7.5, 2.0)) * (1.0 - phase * 0.25);
}

void main() {
  vec2 uv = v_uv;
  float squeeze = 1.0 + u_breath * 0.028 - u_audio * 0.05 + u_burst * 0.14;
  vec2 p = uv / max(squeeze, 0.2);
  float r = length(p);

  float spin = u_time * (0.16 + 0.5 * u_energy);
  mat3 rot = tiltedSpin(spin);

  vec3 accum = vec3(0.0);
  float density = 0.0;
  float veinLight = 0.0;

  if (r < 1.02) {
    float edge = sqrt(max(0.0, 1.0 - min(r, 1.0) * min(r, 1.0)));
    for (int i = 0; i < LAYERS; i += 1) {
      float fi = float(i) / float(LAYERS - 1);
      float z = (fi - 0.5) * 2.0 * edge * SHELL;
      vec3 pos = vec3(p, z);
      float depth = length(pos);
      if (depth > 1.0) {
        continue;
      }
      vec3 sp = rot * pos;
      float t = u_time * (0.35 + 0.6 * u_energy);
      float cloud = fbm(sp * (2.6 + 1.1 * u_energy) + vec3(0.0, -t * 0.22, t * 0.14), 4);
      cloud = pow(clamp(cloud * 1.35, 0.0, 1.0), 1.5 + 0.8 * (1.0 - u_energy));

      float vein = filaments(sp, t, 5.0 + 3.0 * (1.0 - u_energy));
      float radial = smoothstep(0.14, 0.82, depth) * smoothstep(1.0, 0.72, depth);
      vein *= radial;

      float wave = u_pulse * waveAt(depth, u_pulse);
      float voice = u_audio * exp(-pow((depth - (1.0 - u_audio) * 0.9) * 5.0, 2.0));

      float shellFalloff = smoothstep(1.02, 0.12, depth);
      float mass = shellFalloff * (0.34 + 0.5 * cloud);
      float body = cloud * shellFalloff * (0.34 + 0.34 * u_energy);
      float local = body + mass * 0.55 + vein * (1.75 + 1.0 * u_energy);
      local += wave * 1.6 + voice * 0.9;

      vec3 tint = mix(u_deep, u_body, clamp(cloud * cloud * 1.5, 0.0, 1.0));
      tint = mix(tint, u_pulseColor, clamp(vein * 0.7 + wave, 0.0, 1.0));

      float weight = 1.0 / float(LAYERS);
      accum += tint * local * weight * 2.2;
      density += (local + mass * 0.9) * weight * 1.9;
      veinLight += vein * weight;
    }

    float core = pow(max(0.0, 1.0 - r / 0.34), 2.2) * (0.9 + 0.16 * u_breath);
    vec3 coreColor = mix(u_body, u_rim, 0.45) * core * (1.15 + 0.5 * u_energy);
    accum += coreColor;
    density += core * 0.9;

    float fres = pow(1.0 - edge, 2.4) * smoothstep(1.01, 0.8, r);
    accum += u_rim * fres * (1.35 + 0.5 * u_energy + 0.6 * u_burst);
    density += fres * 1.15;

    float limb = smoothstep(1.01, 0.94, r) * smoothstep(0.82, 0.95, r);
    limb *= 0.45 + 0.55 * clamp(veinLight * 3.0, 0.0, 1.0);
    accum += u_rim * limb * 0.6;
    density += limb * 0.4;

    float sparks = 0.0;
    for (int i = 0; i < 7; i += 1) {
      float fi = float(i);
      float angle = u_time * (1.1 + fi * 0.19) + fi * 2.39996;
      vec3 orbit = rot * vec3(cos(angle) * 0.92, sin(angle * 0.7) * 0.6, sin(angle) * 0.92);
      float near = smoothstep(-1.0, 1.0, orbit.z);
      sparks += exp(-pow(length(p - orbit.xy) * 30.0, 2.0)) * (0.4 + 0.6 * near);
    }
    accum += u_spark * sparks * u_energy * 1.25;
    density += sparks * u_energy;
  }

  float glowRadius = 2.35 - 0.5 * u_burst;
  float halo = exp(-r * glowRadius) * u_halo * (0.75 + 0.28 * u_breath + 0.4 * u_energy + 1.4 * u_burst);
  accum += mix(u_body, u_pulseColor, 0.35) * halo;
  density += halo * 0.6;

  float shock = u_burst * exp(-pow((r - u_burst * 1.9) * 4.2, 2.0));
  accum += u_rim * shock * 2.2;
  density += shock;

  float ring = ringMask(p, 1.06) * (0.35 + 0.22 * u_breath) * (1.0 - u_burst);
  accum += u_rim * ring;
  density += ring * 0.55;

  accum = mix(accum, vec3(dot(accum, vec3(0.35, 0.28, 0.28))) + vec3(0.65, 0.13, 0.09) * u_error, u_error * 0.72);

  float alpha = clamp(density, 0.0, 1.0);
  vec3 mapped = accum / (1.0 + accum * 0.55);
  mapped = mix(mapped, accum, 0.25);
  outColor = vec4(mapped, alpha);
}
`;
