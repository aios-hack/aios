export const SPHERE_NOISE = `
float hash(vec3 p) {
  p = fract(p * 0.3183099 + vec3(0.71, 0.113, 0.419));
  p *= 17.0;
  return fract(p.x * p.y * p.z * (p.x + p.y + p.z));
}

float noise(vec3 p) {
  vec3 i = floor(p);
  vec3 f = fract(p);
  f = f * f * (3.0 - 2.0 * f);
  float n000 = hash(i + vec3(0.0, 0.0, 0.0));
  float n100 = hash(i + vec3(1.0, 0.0, 0.0));
  float n010 = hash(i + vec3(0.0, 1.0, 0.0));
  float n110 = hash(i + vec3(1.0, 1.0, 0.0));
  float n001 = hash(i + vec3(0.0, 0.0, 1.0));
  float n101 = hash(i + vec3(1.0, 0.0, 1.0));
  float n011 = hash(i + vec3(0.0, 1.0, 1.0));
  float n111 = hash(i + vec3(1.0, 1.0, 1.0));
  return mix(
    mix(mix(n000, n100, f.x), mix(n010, n110, f.x), f.y),
    mix(mix(n001, n101, f.x), mix(n011, n111, f.x), f.y),
    f.z
  );
}

float fbm(vec3 p, int octaves) {
  float value = 0.0;
  float amplitude = 0.55;
  float scale = 1.0;
  for (int i = 0; i < 5; i += 1) {
    if (i >= octaves) {
      break;
    }
    value += amplitude * noise(p * scale);
    scale *= 2.03;
    amplitude *= 0.52;
  }
  return value;
}

mat3 tiltedSpin(float angle) {
  float c = cos(angle);
  float s = sin(angle);
  mat3 spin = mat3(c, 0.0, -s, 0.0, 1.0, 0.0, s, 0.0, c);
  float tc = cos(0.42);
  float ts = sin(0.42);
  mat3 tilt = mat3(1.0, 0.0, 0.0, 0.0, tc, -ts, 0.0, ts, tc);
  return tilt * spin;
}

vec3 warp(vec3 p, float t, float strength) {
  vec3 q = vec3(
    fbm(p + vec3(0.0, 1.7, 4.2) + t * 0.11, 2),
    fbm(p + vec3(3.1, 0.0, 1.3) - t * 0.09, 2),
    fbm(p + vec3(1.9, 5.4, 0.0) + t * 0.13, 2)
  );
  return p + (q - 0.5) * strength;
}

float filaments(vec3 p, float t, float sharpness) {
  float depth = max(length(p), 0.001);
  vec3 dir = p / depth;
  vec3 radial = dir * (1.0 + depth * 0.35);
  vec3 w = warp(radial * 2.4, t, 0.55);
  float veins = fbm(w * 1.9 + vec3(0.0, t * 0.12, 0.0), 3);
  float ridged = 1.0 - abs(veins * 2.0 - 1.0);
  float strands = pow(clamp(ridged, 0.0, 1.0), sharpness);
  float taper = smoothstep(0.0, 0.35, depth) * smoothstep(1.05, 0.55, depth);
  return strands * taper;
}
`;
