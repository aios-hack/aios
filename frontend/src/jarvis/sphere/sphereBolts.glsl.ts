export const SPHERE_BOLTS = `
vec3 seedDirection(float seed) {
  float a = fract(sin(seed * 12.9898) * 43758.5453) * 6.2831853;
  float z = fract(sin(seed * 78.233) * 12345.6789) * 2.0 - 1.0;
  float rad = sqrt(max(0.0, 1.0 - z * z));
  return vec3(cos(a) * rad, sin(a) * rad, z);
}

vec3 orthogonal(vec3 axis, float seed) {
  vec3 helper = abs(axis.y) < 0.9 ? vec3(0.0, 1.0, 0.0) : vec3(1.0, 0.0, 0.0);
  vec3 first = normalize(cross(axis, helper));
  vec3 second = cross(axis, first);
  float twist = fract(sin(seed * 33.719) * 9182.317) * 6.2831853;
  return normalize(first * cos(twist) + second * sin(twist));
}

float boltStroke(
  vec2 p,
  float edge,
  mat3 rot,
  vec4 bolt,
  vec2 pointer,
  float pixel,
  float flow
) {
  float strength = bolt.w;
  if (strength <= 0.001) {
    return 0.0;
  }
  vec3 start = seedDirection(bolt.x);
  vec3 side = orthogonal(start, bolt.x + 1.7);
  vec3 pull = vec3(pointer, 0.35);
  float aim = clamp(length(pointer), 0.0, 1.0);
  vec3 target = normalize(mix(side, normalize(pull + side * 0.4), aim * 0.6));
  vec3 axis = normalize(cross(start, target));
  vec3 perp = normalize(cross(axis, start));

  float progress = clamp(bolt.y, 0.0, 1.0);
  float arc = 1.05 + 0.55 * fract(bolt.x * 0.371);
  float best = 1.0e3;
  float head = 0.0;
  for (int i = 0; i < 18; i += 1) {
    float s = float(i) / 17.0;
    if (s > progress + 0.08) {
      break;
    }
    float ang = s * arc;
    vec3 point = start * cos(ang) + perp * sin(ang);
    float jitter = fbm(point * 3.4 + vec3(bolt.x, flow * 0.35, 0.0), 3) - 0.5;
    vec3 wobble = normalize(point + axis * jitter * 0.22);
    vec3 view = rot * wobble;
    if (view.z < -0.15) {
      continue;
    }
    float d = length(p - view.xy);
    float depthFade = smoothstep(-0.15, 0.45, view.z);
    float behind = clamp((progress + 0.06 - s) / 0.61, 0.0, 1.0);
    float trail = behind * behind * (3.0 - 2.0 * behind);
    float lit = max(depthFade * trail, 0.001);
    if (d < best) {
      best = d;
      head = lit;
    }
  }
  if (head <= 0.001) {
    return 0.0;
  }
  float core = 1.0 - smoothstep(pixel * 0.8, pixel * 3.0, best);
  float glow = exp(-best * 22.0) * 0.7;
  float inside = smoothstep(0.02, 0.2, edge);
  return (core + glow) * head * strength * inside;
}

float boltField(
  vec2 p,
  float edge,
  mat3 rot,
  vec4 bolts[4],
  vec2 pointer,
  float pixel,
  float flow
) {
  float total = 0.0;
  for (int i = 0; i < 4; i += 1) {
    total += boltStroke(p, edge, rot, bolts[i], pointer, pixel, flow);
  }
  return min(total, 2.2);
}
`;
