import { configure } from '@testing-library/react';
import { afterEach, beforeEach, vi } from 'vitest';
import { clearJsonCache } from '../data/jsonCache';

configure({ asyncUtilTimeout: 5000 });

const canvasContextStub = (): CanvasRenderingContext2D =>
  ({
    setTransform: vi.fn(),
    clearRect: vi.fn(),
    fillRect: vi.fn(),
    strokeRect: vi.fn(),
    beginPath: vi.fn(),
    closePath: vi.fn(),
    moveTo: vi.fn(),
    lineTo: vi.fn(),
    arc: vi.fn(),
    fill: vi.fn(),
    stroke: vi.fn(),
    save: vi.fn(),
    restore: vi.fn(),
    translate: vi.fn(),
    scale: vi.fn(),
    fillText: vi.fn(),
    measureText: vi.fn(() => ({ width: 0 }) as TextMetrics),
    setLineDash: vi.fn(),
    globalAlpha: 1,
    lineWidth: 1,
    font: '',
    textAlign: 'left',
    textBaseline: 'alphabetic',
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
