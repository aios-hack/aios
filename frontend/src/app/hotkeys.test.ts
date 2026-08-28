import { describe, expect, it } from 'vitest';
import { isEditableTarget, isInsideScroller } from './useHotkeys';

const element = (tag: string, style: Partial<CSSStyleDeclaration> = {}): HTMLElement => {
  const node = document.createElement(tag);
  Object.assign(node.style, style);
  return node;
};

const withScroll = (node: HTMLElement, scrollHeight: number, clientHeight: number): HTMLElement => {
  Object.defineProperty(node, 'scrollHeight', { value: scrollHeight, configurable: true });
  Object.defineProperty(node, 'clientHeight', { value: clientHeight, configurable: true });
  return node;
};

describe('isEditableTarget', () => {
  it('recognises the fields that own their own keys', () => {
    expect(isEditableTarget(element('input'))).toBe(true);
    expect(isEditableTarget(element('textarea'))).toBe(true);
    expect(isEditableTarget(element('select'))).toBe(true);
  });

  it('leaves plain elements to the global shortcuts', () => {
    expect(isEditableTarget(element('div'))).toBe(false);
    expect(isEditableTarget(null)).toBe(false);
  });
});

describe('isInsideScroller', () => {
  it('spots the scroller the key press belongs to', () => {
    const scroller = withScroll(element('div', { overflowY: 'auto' }), 2000, 800);
    document.body.append(scroller);
    expect(isInsideScroller(scroller)).toBe(true);
    scroller.remove();
  });

  it('walks up to a scrolling ancestor, since the key lands on the deepest node', () => {
    const scroller = withScroll(element('div', { overflowY: 'auto' }), 2000, 800);
    const row = element('td');
    scroller.append(row);
    document.body.append(scroller);
    expect(isInsideScroller(row)).toBe(true);
    scroller.remove();
  });

  it('ignores a container that has nothing to scroll', () => {
    const still = withScroll(element('div', { overflowY: 'auto' }), 400, 400);
    document.body.append(still);
    expect(isInsideScroller(still)).toBe(false);
    still.remove();
  });

  it('ignores overflowing content that was never made scrollable', () => {
    const clipped = withScroll(element('div', { overflowY: 'hidden' }), 2000, 800);
    document.body.append(clipped);
    expect(isInsideScroller(clipped)).toBe(false);
    clipped.remove();
  });

  it('reports nothing for a target outside the document', () => {
    expect(isInsideScroller(null)).toBe(false);
  });
});
