export const layerColors = {
  layer1: 'var(--color-layer-1)',
  layer2: 'var(--color-layer-2)',
  both: 'var(--color-layer-both)',
  dim: 'var(--color-well-dim)'
} as const;

export const graphColors = {
  injector: 'var(--color-graph-injector)',
  producer: 'var(--color-graph-producer)',
  edge: 'var(--color-graph-edge)',
  dim: 'var(--color-well-dim)',
  text: 'var(--color-text)',
  muted: 'var(--color-text-muted)'
} as const;

export const fluidColors = {
  oil: 'var(--color-oil)',
  oilStrong: 'var(--color-oil-strong)',
  water: 'var(--color-water)',
  waterPale: 'var(--color-water-pale)',
  unknown: 'var(--color-unknown)'
} as const;


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
