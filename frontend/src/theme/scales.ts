export const clamp01 = (value: number): number =>
  value <= 0 ? 0 : value >= 1 ? 1 : value;

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
