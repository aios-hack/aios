import { configure } from '@testing-library/react';
import { afterEach, beforeEach, vi } from 'vitest';
import { clearJsonCache } from '../data/jsonCache';

configure({ asyncUtilTimeout: 5000 });

// Node 25 exposes an experimental global `localStorage` which is incomplete
// unless the process is started with a backing file.  Vitest's globals can
// shadow jsdom's fully functional storage with that object, so provide the
// deterministic in-memory implementation the UI tests actually need.
class TestStorage implements Storage {
  private readonly values = new Map<string, string>();

  get length() {
    return this.values.size;
  }

  clear() {
    this.values.clear();
  }

  getItem(key: string) {
    return this.values.get(key) ?? null;
  }

  key(index: number) {
    return [...this.values.keys()][index] ?? null;
  }

  removeItem(key: string) {
    this.values.delete(key);
  }

  setItem(key: string, value: string) {
    this.values.set(key, String(value));
  }
}

const testLocalStorage = new TestStorage();
Object.defineProperty(globalThis, 'localStorage', {
  configurable: true,
  value: testLocalStorage
});
Object.defineProperty(window, 'localStorage', {
  configurable: true,
  value: testLocalStorage
});

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
  testLocalStorage.clear();
});

afterEach(() => {
  clearJsonCache();
});
