import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { describe, expect, it } from 'vitest';

const themeFile = (name: string): string =>
  readFileSync(join(process.cwd(), 'src', 'theme', name), 'utf-8');

const readToken = (css: string, name: string): string => {
  const match = css.match(new RegExp(`${name}:\\s*([^;]+);`));
  if (match === null) {
    throw new Error(`token ${name} not found`);
  }
  return match[1].trim();
};

const hexToRgb = (hex: string): number[] => {
  const clean = hex.replace('#', '');
  return [0, 2, 4].map((i) => parseInt(clean.slice(i, i + 2), 16));
};

const hueOf = ([r, g, b]: number[]): number => {
  const [mx, mn] = [Math.max(r, g, b), Math.min(r, g, b)];
  const d = mx - mn;
  if (d === 0) {
    return 0;
  }
  const raw =
    mx === r ? 60 * (((g - b) / d) % 6) : mx === g ? 60 * ((b - r) / d + 2) : 60 * ((r - g) / d + 4);
  return raw < 0 ? raw + 360 : raw;
};

const CHUNK_HEADER = 8;
const RGBA_STRIDE = 4;
const OPAQUE = 200;
const COLOURED = 0.25;

const inflate = (data: Uint8Array): Uint8Array => {
  const { inflateSync } = require('node:zlib') as typeof import('node:zlib');
  return new Uint8Array(inflateSync(Buffer.from(data)));
};

const paeth = (a: number, b: number, c: number): number => {
  const p = a + b - c;
  const [pa, pb, pc] = [Math.abs(p - a), Math.abs(p - b), Math.abs(p - c)];
  return pa <= pb && pa <= pc ? a : pb <= pc ? b : c;
};

interface Decoded {
  width: number;
  height: number;
  pixels: Uint8Array;
}

const decodePng = (file: Buffer): Decoded => {
  const view = new DataView(file.buffer, file.byteOffset, file.byteLength);
  let offset = CHUNK_HEADER;
  let width = 0;
  let height = 0;
  const idat: Uint8Array[] = [];

  while (offset < file.length) {
    const length = view.getUint32(offset);
    const type = String.fromCharCode(...file.subarray(offset + 4, offset + 8));
    const body = file.subarray(offset + 8, offset + 8 + length);
    if (type === 'IHDR') {
      width = view.getUint32(offset + 8);
      height = view.getUint32(offset + 12);
      expect(body[8], 'bit depth').toBe(8);
      expect(body[9], 'colour type must be RGBA').toBe(6);
    }
    if (type === 'IDAT') {
      idat.push(new Uint8Array(body));
    }
    if (type === 'IEND') {
      break;
    }
    offset += 12 + length;
  }

  const merged = new Uint8Array(idat.reduce((n, part) => n + part.length, 0));
  let cursor = 0;
  for (const part of idat) {
    merged.set(part, cursor);
    cursor += part.length;
  }

  const raw = inflate(merged);
  const stride = width * RGBA_STRIDE;
  const pixels = new Uint8Array(width * height * RGBA_STRIDE);

  for (let y = 0; y < height; y += 1) {
    const filter = raw[y * (stride + 1)];
    const line = raw.subarray(y * (stride + 1) + 1, y * (stride + 1) + 1 + stride);
    for (let x = 0; x < stride; x += 1) {
      const left = x >= RGBA_STRIDE ? pixels[y * stride + x - RGBA_STRIDE] : 0;
      const up = y > 0 ? pixels[(y - 1) * stride + x] : 0;
      const upLeft = y > 0 && x >= RGBA_STRIDE ? pixels[(y - 1) * stride + x - RGBA_STRIDE] : 0;
      const value =
        filter === 0
          ? line[x]
          : filter === 1
            ? line[x] + left
            : filter === 2
              ? line[x] + up
              : filter === 3
                ? line[x] + ((left + up) >> 1)
                : line[x] + paeth(left, up, upLeft);
      pixels[y * stride + x] = value & 0xff;
    }
  }

  return { width, height, pixels };
};

const dominantHue = (file: Buffer): number => {
  const { pixels } = decodePng(file);
  const counts = new Map<number, number>();
  for (let i = 0; i < pixels.length; i += RGBA_STRIDE) {
    if (pixels[i + 3] < OPAQUE) {
      continue;
    }
    const rgb = [pixels[i], pixels[i + 1], pixels[i + 2]];
    const mx = Math.max(...rgb);
    if (mx === 0 || (mx - Math.min(...rgb)) / mx < COLOURED) {
      continue;
    }
    const hue = Math.round(hueOf(rgb));
    counts.set(hue, (counts.get(hue) ?? 0) + 1);
  }
  expect(counts.size, 'the mark has coloured pixels').toBeGreaterThan(0);
  return [...counts.entries()].sort((a, b) => b[1] - a[1])[0][0];
};

const logoFile = (name: string): Buffer =>
  readFileSync(join(process.cwd(), 'public', 'brand', `${name}.png`));

describe('the mark wears the accent of the theme it appears in', () => {
  const themes = [
    { file: 'bsr-light', tokens: 'tokens.light.css' },
    { file: 'bsr-dark', tokens: 'tokens.dark.css' }
  ];

  for (const theme of themes) {
    it(`${theme.file} carries the same hue as --color-accent`, () => {
      const accent = hueOf(hexToRgb(readToken(themeFile(theme.tokens), '--color-accent')));
      const mark = dominantHue(logoFile(theme.file));
      const gap = Math.abs(accent - mark);
      expect(Math.min(gap, 360 - gap), `${theme.file} vs accent`).toBeLessThanOrEqual(6);
    });
  }

  it('keeps a neutral tagline instead of tinting the whole mark', () => {
    const { pixels } = decodePng(logoFile('bsr-light'));
    let neutral = 0;
    for (let i = 0; i < pixels.length; i += RGBA_STRIDE) {
      if (pixels[i + 3] < OPAQUE) {
        continue;
      }
      const rgb = [pixels[i], pixels[i + 1], pixels[i + 2]];
      const mx = Math.max(...rgb);
      if (mx < 90 && (mx === 0 || (mx - Math.min(...rgb)) / mx < COLOURED)) {
        neutral += 1;
      }
    }
    expect(neutral, 'dark tagline pixels survive the recolour').toBeGreaterThan(1000);
  });
});
