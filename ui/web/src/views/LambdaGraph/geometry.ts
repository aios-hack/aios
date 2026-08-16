export const trianglePath = (x: number, y: number, r: number): string =>
  `M ${x} ${y + r * 1.15} L ${x + r} ${y - r * 0.8} L ${x - r} ${y - r * 0.8} Z`;
