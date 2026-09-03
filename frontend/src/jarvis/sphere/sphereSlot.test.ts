import { describe, expect, it } from 'vitest';
import { centerOf, readSlot, type SlotRect } from './sphereSlot';

const navSlot: SlotRect = { left: 16, top: 346, width: 108, height: 108 };

describe('reading a slot from the document', () => {
  it('returns the rectangle of a laid out element', () => {
    const element = {
      getBoundingClientRect: () => ({ left: 10, top: 20, width: 30, height: 40 })
    } as unknown as Element;
    expect(readSlot(element)).toEqual({ left: 10, top: 20, width: 30, height: 40 });
  });

  it('refuses a missing element or one with no box', () => {
    expect(readSlot(null)).toBeNull();
    const collapsed = {
      getBoundingClientRect: () => ({ left: 0, top: 0, width: 0, height: 0 })
    } as unknown as Element;
    expect(readSlot(collapsed)).toBeNull();
  });

  it('refuses something that is not laid out at all', () => {
    expect(readSlot({} as unknown as Element)).toBeNull();
  });
});

describe('the centre of a slot', () => {
  it('sits half a box in from each edge', () => {
    expect(centerOf(navSlot)).toEqual({ x: 70, y: 400 });
  });
});
