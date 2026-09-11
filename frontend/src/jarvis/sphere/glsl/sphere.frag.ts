import { SPHERE_NOISE } from '@/jarvis/sphere/glsl/sphereNoise.glsl';
import { SPHERE_BOLTS } from '@/jarvis/sphere/glsl/sphereBolts.glsl';

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

uniform float u_spin;
uniform float u_flow;
uniform float u_breath;
uniform float u_energy;
uniform float u_audio;
uniform float u_error;
uniform float u_burst;
uniform float u_theme;
uniform float u_halo;
uniform float u_pixel;
uniform vec2 u_pointer;
uniform vec4 u_bolts[4];
uniform vec3 u_body;
uniform vec3 u_pulseColor;
uniform vec3 u_deep;
uniform vec3 u_rim;
uniform vec3 u_spark;
uniform vec3 u_shadow;

${SPHERE_NOISE}
${SPHERE_BOLTS}

const int LAYERS = 5;
const float SHELL = 0.86;

void main() {
  vec2 uv = v_uv;
  float squeeze = 1.0 + u_breath * 0.012 - u_audio * 0.05 + u_burst * 0.14;
  vec2 p = uv / max(squeeze, 0.2);
  float r = length(p);
  float light = u_theme;

  mat3 rot = tiltedSpin(u_spin);

  vec3 accum = vec3(0.0);
  float density = 0.0;
  float veinLight = 0.0;
  float boltLight = 0.0;

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
      float t = u_flow;
      float cloud = fbm(sp * (2.6 + 1.1 * u_energy) + vec3(0.0, -t * 0.22, t * 0.14), 4);
      cloud = pow(clamp(cloud * 1.35, 0.0, 1.0), 1.5 + 0.8 * (1.0 - u_energy));

      float vein = filaments(sp, t, 5.0 + 3.0 * (1.0 - u_energy)) * 0.7;
      float radial = smoothstep(0.14, 0.82, depth) * smoothstep(1.0, 0.72, depth);
      vein *= radial;

      float voice = u_audio * exp(-pow((depth - (1.0 - u_audio) * 0.9) * 5.0, 2.0));

      float shellFalloff = smoothstep(1.02, 0.12, depth);
      float mass = shellFalloff * (0.34 + 0.5 * cloud);
      float body = cloud * shellFalloff * (0.34 + 0.34 * u_energy);
      float local = body + mass * (0.55 + 0.55 * light) + vein * (1.75 + 1.0 * u_energy);
      local += voice * 0.9;

      vec3 tint = mix(u_deep, u_body, clamp(cloud * cloud * 1.5, 0.0, 1.0));
      tint = mix(tint, u_pulseColor, clamp(vein * 0.7, 0.0, 1.0));

      float weight = 1.0 / float(LAYERS);
      accum += tint * local * weight * 2.2;
      density += (local + mass * 0.9) * weight * (1.9 + 1.1 * light);
      veinLight += vein * weight;
    }

    float core = pow(max(0.0, 1.0 - r / 0.34), 2.2) * (0.95 + 0.05 * u_breath);
    vec3 coreColor = mix(u_body, u_rim, mix(0.45, 0.2, light)) * core * (1.15 + 0.5 * u_energy);
    accum += coreColor;
    density += core * 0.9;

    float fres = pow(1.0 - edge, 2.4) * smoothstep(1.01, 0.8, r);
    accum += u_rim * fres * (1.35 + 0.5 * u_energy + 0.6 * u_burst);
    density += fres * 1.15;

    float limb = smoothstep(1.01, 0.94, r) * smoothstep(0.82, 0.95, r);
    limb *= 0.45 + 0.55 * clamp(veinLight * 3.0, 0.0, 1.0);
    accum += u_rim * limb * 0.6;
    density += limb * 0.4;

    boltLight = boltField(p, edge, rot, u_bolts, u_pointer, u_pixel, u_flow);
    vec3 boltColor = mix(u_rim, u_pulseColor, 0.35);
    accum += boltColor * boltLight * (2.4 - 0.9 * light);
    density += boltLight * 1.2;

    float sparks = 0.0;
    for (int i = 0; i < 7; i += 1) {
      float fi = float(i);
      float angle = u_flow * (1.1 + fi * 0.19) + fi * 2.39996;
      vec3 orbit = rot * vec3(cos(angle) * 0.92, sin(angle * 0.7) * 0.6, sin(angle) * 0.92);
      float near = smoothstep(-1.0, 1.0, orbit.z);
      sparks += exp(-pow(length(p - orbit.xy) * 30.0, 2.0)) * (0.4 + 0.6 * near);
    }
    accum += u_spark * sparks * u_energy * 1.25;
    density += sparks * u_energy;
  }

  float glowRadius = 2.35 - 0.5 * u_burst;
  float haloMask = exp(-r * glowRadius) * u_halo;
  float halo = haloMask * (0.75 + 0.12 * u_breath + 0.4 * u_energy + 1.4 * u_burst);
  accum += mix(u_body, u_pulseColor, 0.35) * halo * (1.0 - light);
  density += halo * 0.6 * (1.0 - light);

  vec2 sp = vec2(p.x, (p.y + 0.5) * 1.9);
  float shade = exp(-pow(length(sp) * 1.35, 2.2)) * smoothstep(0.0, -0.2, p.y);
  float shadow = shade * u_halo * light * (0.9 + 0.2 * u_burst);
  accum += u_shadow * shadow;
  density += shadow * 0.85;

  float shock = u_burst * exp(-pow((r - u_burst * 1.9) * 4.2, 2.0));
  accum += u_rim * shock * 2.2;
  density += shock;

  accum = mix(accum, vec3(dot(accum, vec3(0.35, 0.28, 0.28))) + vec3(0.65, 0.13, 0.09) * u_error, u_error * 0.72);

  float alpha = clamp(density, 0.0, 1.0);
  vec3 mapped = accum / (1.0 + accum * 0.55);
  mapped = mix(mapped, accum, 0.25);
  vec3 solid = mix(u_deep, u_body, clamp(dot(mapped, vec3(0.9)), 0.0, 1.0));
  vec3 lit = mix(solid, mapped, 0.45) + boltLight * u_rim * 0.9;
  outColor = mix(vec4(mapped, alpha), vec4(lit * alpha, alpha), light);
}
`;
