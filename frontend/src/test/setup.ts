import { afterEach, beforeEach, vi } from 'vitest';
import { clearJsonCache } from '../data/jsonCache';

const canvasContextStub = (): CanvasRenderingContext2D =>
  ({
    setTransform: vi.fn(),
    clearRect: vi.fn(),
    beginPath: vi.fn(),
    arc: vi.fn(),
    fill: vi.fn(),
    stroke: vi.fn(),
    globalAlpha: 1,
    lineWidth: 1,
    fillStyle: '',
    strokeStyle: ''
  }) as unknown as CanvasRenderingContext2D;

HTMLCanvasElement.prototype.getContext = vi.fn(
  canvasContextStub
) as unknown as HTMLCanvasElement['getContext'];

beforeEach(() => {
  clearJsonCache();
});

afterEach(() => {
  clearJsonCache();
});
