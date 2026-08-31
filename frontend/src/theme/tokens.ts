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

export const wallMarkColors = {
  line: 'var(--color-oil-strong)',
  fill: 'var(--scale-watercut-1)',
  shut: 'var(--color-axis-tick)',
  idle: 'var(--color-unknown)',
  cursor: 'var(--color-accent)'
} as const;
