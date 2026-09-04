export const groupPalette = [
  'var(--color-group-1)',
  'var(--color-group-2)',
  'var(--color-group-3)',
  'var(--color-group-4)',
  'var(--color-group-5)',
  'var(--color-group-6)'
] as const;

export const groupColor = (index: number): string =>
  groupPalette[((index % groupPalette.length) + groupPalette.length) % groupPalette.length];

export const chronoModeColors = {
  production: 'var(--color-oil)',
  injection: 'var(--color-injection)',
  shut: 'var(--color-surface-sunken)',
  idle: 'var(--color-well-dim)'
} as const;

export const edgeColors = {
  positive: 'var(--color-edge-positive)',
  negative: 'var(--color-edge-negative)'
} as const;

export const EDGE_OPACITY_FLOOR = 0.1;
export const EDGE_OPACITY_SPAN = 0.62;
export const EDGE_WIDTH_FLOOR = 0.12;
export const EDGE_WIDTH_SPAN = 0.98;
export const EDGE_WIDTH_FLAT = 0.4;

export const wallMarkColors = {
  line: 'var(--color-oil-strong)',
  fill: 'var(--scale-watercut-1)',
  shut: 'var(--color-axis-tick)',
  idle: 'var(--color-unknown)',
  cursor: 'var(--color-accent)'
} as const;
