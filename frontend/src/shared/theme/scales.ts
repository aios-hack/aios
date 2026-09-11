import { clamp01 } from '@/shared/lib/math/clamp';

export { clamp01 };
export const watercutColor = (watercut: number | null): string => {
  if (watercut === null || Number.isNaN(watercut)) {
    return 'var(--color-unknown)';
  }
  const share = clamp01(watercut);
  return `color-mix(in oklab, var(--scale-watercut-1) ${(share * 100).toFixed(1)}%, var(--scale-watercut-0))`;
};

export const ratioColor = (ratio: number | null): string => {
  if (ratio === null || Number.isNaN(ratio)) {
    return 'var(--color-unknown)';
  }
  if (ratio >= 1) {
    return 'var(--scale-ratio-high)';
  }
  const share = clamp01(ratio);
  return `color-mix(in oklab, var(--scale-ratio-mid) ${(share * 100).toFixed(1)}%, var(--scale-ratio-low))`;
};

export const areaRadius = (
  value: number,
  maximum: number,
  minRadius: number,
  maxRadius: number
): number => {
  if (maximum <= 0 || value <= 0 || Number.isNaN(value)) {
    return minRadius;
  }
  const share = Math.sqrt(clamp01(value / maximum));
  return minRadius + (maxRadius - minRadius) * share;
};

export const SEQ_STOPS = 7;

export const mapRampColor = (share: number): string => {
  const bounded = clamp01(share);
  const position = bounded * (SEQ_STOPS - 1);
  const low = Math.min(Math.floor(position), SEQ_STOPS - 2);
  const mix = position - low;
  const percent = (mix * 100).toFixed(1);
  return `color-mix(in oklab, var(--color-map-seq-${low + 1}) ${percent}%, var(--color-map-seq-${low}))`;
};
