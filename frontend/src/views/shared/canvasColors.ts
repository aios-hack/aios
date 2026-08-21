import { clamp01 } from '../../theme/scales';

export interface Rgb {
  r: number;
  g: number;
  b: number;
  a: number;
}

const HEX = /^#([0-9a-f]{3,8})$/i;
const FUNCTIONAL = /^rgba?\(([^)]+)\)$/i;

const expandShort = (digits: string): string =>
  digits
    .split('')
    .map((digit) => digit + digit)
    .join('');

const fromHex = (digits: string): Rgb | null => {
  const full =
    digits.length === 3 || digits.length === 4 ? expandShort(digits) : digits;
  if (full.length !== 6 && full.length !== 8) {
    return null;
  }
  const value = Number.parseInt(full, 16);
  if (Number.isNaN(value)) {
    return null;
  }
  if (full.length === 6) {
    return { r: (value >> 16) & 255, g: (value >> 8) & 255, b: value & 255, a: 1 };
  }
  return {
    r: (value >>> 24) & 255,
    g: (value >>> 16) & 255,
    b: (value >>> 8) & 255,
    a: (value & 255) / 255
  };
};

const fromFunctional = (body: string): Rgb | null => {
  const parts = body
    .split(/[\s,/]+/)
    .map((part) => part.trim())
    .filter((part) => part.length > 0);
  if (parts.length < 3) {
    return null;
  }
  const channels = parts.slice(0, 3).map(Number);
  if (channels.some(Number.isNaN)) {
    return null;
  }
  const alphaRaw = parts[3];
  const alpha =
    alphaRaw === undefined
      ? 1
      : alphaRaw.endsWith('%')
        ? Number(alphaRaw.slice(0, -1)) / 100
        : Number(alphaRaw);
  return {
    r: channels[0],
    g: channels[1],
    b: channels[2],
    a: Number.isNaN(alpha) ? 1 : clamp01(alpha)
  };
};

export const parseColor = (input: string): Rgb | null => {
  const text = input.trim();
  if (text.length === 0) {
    return null;
  }
  const hex = HEX.exec(text);
  if (hex !== null) {
    return fromHex(hex[1]);
  }
  const functional = FUNCTIONAL.exec(text);
  if (functional !== null) {
    return fromFunctional(functional[1]);
  }
  return null;
};

export const toCanvasColor = ({ r, g, b, a }: Rgb): string => {
  const round = (channel: number): number => Math.round(clamp01(channel / 255) * 255);
  if (a >= 1) {
    return `rgb(${round(r)}, ${round(g)}, ${round(b)})`;
  }
  return `rgba(${round(r)}, ${round(g)}, ${round(b)}, ${clamp01(a).toFixed(3)})`;
};

export const mixColors = (from: Rgb, to: Rgb, share: number): Rgb => {
  const t = clamp01(share);
  return {
    r: from.r + (to.r - from.r) * t,
    g: from.g + (to.g - from.g) * t,
    b: from.b + (to.b - from.b) * t,
    a: from.a + (to.a - from.a) * t
  };
};

export const readCssColor = (name: string, root: Element | null): Rgb | null => {
  if (root === null || typeof getComputedStyle !== 'function') {
    return null;
  }
  const raw = getComputedStyle(root).getPropertyValue(name);
  return parseColor(raw);
};

export const readPalette = <Name extends string>(
  names: readonly Name[],
  fallback: Rgb,
  root: Element | null
): Record<Name, Rgb> => {
  const palette = {} as Record<Name, Rgb>;
  for (const name of names) {
    palette[name] = readCssColor(name, root) ?? fallback;
  }
  return palette;
};

export const devicePixelRatioOf = (): number => {
  const ratio = typeof window === 'undefined' ? 1 : window.devicePixelRatio;
  return typeof ratio === 'number' && ratio > 0 ? ratio : 1;
};

export const sameColor = (a: Rgb, b: Rgb): boolean =>
  a.r === b.r && a.g === b.g && a.b === b.b && a.a === b.a;

export const samePalette = <Name extends string>(
  a: Record<Name, Rgb>,
  b: Record<Name, Rgb>
): boolean => {
  const names = Object.keys(a) as Name[];
  return (
    names.length === Object.keys(b).length &&
    names.every((name) => b[name] !== undefined && sameColor(a[name], b[name]))
  );
};
